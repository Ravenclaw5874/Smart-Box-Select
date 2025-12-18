bl_info = {
    "name": "Smart Box Select",
    "author": "R4V3N",
    "version": (1, 0, 2),
    "blender": (4, 2, 0),
    "location": "View3D > Toolbar",
    "description": "Box/Lasso select with object activation. Clicks select single objects.",
    "category": "Selection",
}

import bpy
import gpu
from gpu_extras.batch import batch_for_shader
from bpy_extras import view3d_utils
from mathutils import Vector

# =========================================================================
# Helper Functions: 계산 및 로직
# =========================================================================

def is_point_in_polygon(point, poly):
    """
    Ray-casting algorithm to check if a point is inside a polygon.
    point: (x, y) tuple or vector
    poly: list of (x, y) tuples or vectors
    """
    x, y = point
    inside = False
    n = len(poly)
    
    p1x, p1y = poly[0]
    for i in range(n + 1):
        p2x, p2y = poly[i % n]
        if y > min(p1y, p2y):
            if y <= max(p1y, p2y):
                if x <= max(p1x, p2x):
                    if p1y != p2y:
                        xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    else:
                        xinters = p1x # 수평선 처리
                        
                    if p1x == p2x or x <= xinters:
                        inside = not inside
        p1x, p1y = p2x, p2y
        
    return inside

def find_closest_and_set_active(context, mouse_co_2d):
    """선택된 오브젝트 중 마우스와 가장 가까운 것을 Active로 설정"""
    selected_objects = context.selected_objects
    if not selected_objects:
        return

    min_dist = float('inf')
    closest_obj = None

    region = context.region
    region_3d = context.space_data.region_3d

    for obj in selected_objects:
        loc_3d = obj.matrix_world.translation
        loc_2d = view3d_utils.location_3d_to_region_2d(region, region_3d, loc_3d)

        if loc_2d:
            dist = (loc_2d - mouse_co_2d).length
            if dist < min_dist:
                min_dist = dist
                closest_obj = obj

    if closest_obj:
        context.view_layer.objects.active = closest_obj


# =========================================================================
# 1. Smart Box Select Operator
# =========================================================================
class VIEW3D_OT_smart_box_select(bpy.types.Operator):
    """Smart Box Select Operator"""
    bl_idname = "view3d.smart_box_select"
    bl_label = "Smart Box Select"
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        if context.space_data.type != 'VIEW_3D':
            return {'CANCELLED'}

        self.start_mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        self.end_mouse = self.start_mouse
        self.is_dragging = True
        
        self._handle = bpy.types.SpaceView3D.draw_handler_add(self.draw_callback_px, (context,), 'WINDOW', 'POST_PIXEL')
        context.window_manager.modal_handler_add(self)
        
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        context.area.tag_redraw()

        if event.type == 'MOUSEMOVE':
            self.end_mouse = Vector((event.mouse_region_x, event.mouse_region_y))

        elif event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            self.end_mouse = Vector((event.mouse_region_x, event.mouse_region_y))
            self.finish(context, event)
            return {'FINISHED'}

        elif event.type in {'RIGHTMOUSE', 'ESC'}:
            self.cancel(context)
            return {'CANCELLED'}

        return {'RUNNING_MODAL'}

    def finish(self, context, event):
        if getattr(self, '_handle', None):
            bpy.types.SpaceView3D.draw_handler_remove(self._handle, 'WINDOW')
            self._handle = None
        
        # --- [수정됨] 클릭 판별 로직 추가 ---
        # 시작점과 끝점 사이의 거리가 5픽셀 미만이면 단순 클릭으로 처리
        drag_distance = (self.end_mouse - self.start_mouse).length
        if drag_distance < 5.0:
            bpy.ops.view3d.select(
                extend=event.shift,
                deselect=event.ctrl,
                toggle=event.shift, # 보통 Shift 클릭은 토글 동작
                location=(int(self.end_mouse.x), int(self.end_mouse.y))
            )
            return
        # -----------------------------------

        xmin = int(min(self.start_mouse.x, self.end_mouse.x))
        xmax = int(max(self.start_mouse.x, self.end_mouse.x))
        ymin = int(min(self.start_mouse.y, self.end_mouse.y))
        ymax = int(max(self.start_mouse.y, self.end_mouse.y))

        sel_mode = 'SET'
        if event.shift and not event.ctrl:
            sel_mode = 'ADD'
        elif event.ctrl and not event.shift:
            sel_mode = 'SUB'
        elif event.ctrl and event.shift:
            sel_mode = 'ADD' 

        bpy.ops.view3d.select_box(
            xmin=xmin, xmax=xmax, 
            ymin=ymin, ymax=ymax, 
            mode=sel_mode
        )

        find_closest_and_set_active(context, self.end_mouse)

    def cancel(self, context):
        if getattr(self, '_handle', None):
            bpy.types.SpaceView3D.draw_handler_remove(self._handle, 'WINDOW')
            self._handle = None
        context.area.tag_redraw()

    def draw_callback_px(self, context):
        if not getattr(self, 'is_dragging', False):
            return

        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        vertices = (
            (self.start_mouse.x, self.start_mouse.y),
            (self.end_mouse.x, self.start_mouse.y),
            (self.end_mouse.x, self.end_mouse.y),
            (self.start_mouse.x, self.end_mouse.y),
        )
        
        # 내부 채우기
        batch_fill = batch_for_shader(shader, 'TRI_FAN', {"pos": vertices})
        gpu.state.blend_set('ALPHA')
        shader.bind()
        shader.uniform_float("color", (0.8, 0.8, 0.8, 0.1))
        batch_fill.draw(shader)
        
        # 테두리
        batch_line = batch_for_shader(shader, 'LINE_LOOP', {"pos": vertices})
        shader.uniform_float("color", (1.0, 1.0, 1.0, 0.5))
        batch_line.draw(shader)
        gpu.state.blend_set('NONE')


# =========================================================================
# 2. Smart Lasso Select Operator
# =========================================================================
class VIEW3D_OT_smart_lasso_select(bpy.types.Operator):
    """Smart Lasso Select Operator (Manual Implementation)"""
    bl_idname = "view3d.smart_lasso_select"
    bl_label = "Smart Lasso Select"
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        if context.space_data.type != 'VIEW_3D':
            return {'CANCELLED'}

        self.path = [Vector((event.mouse_region_x, event.mouse_region_y))]
        self.is_dragging = True

        self._handle = bpy.types.SpaceView3D.draw_handler_add(self.draw_callback_px, (context,), 'WINDOW', 'POST_PIXEL')
        context.window_manager.modal_handler_add(self)
        
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        context.area.tag_redraw()

        if event.type == 'MOUSEMOVE':
            pos = Vector((event.mouse_region_x, event.mouse_region_y))
            # 성능 최적화: 너무 가까운 점은 무시
            if len(self.path) == 0 or (pos - self.path[-1]).length_squared > 2.0:
                self.path.append(pos)

        elif event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            self.finish(context, event)
            return {'FINISHED'}

        elif event.type in {'RIGHTMOUSE', 'ESC'}:
            self.cancel(context)
            return {'CANCELLED'}

        return {'RUNNING_MODAL'}

    def finish(self, context, event):
        if getattr(self, '_handle', None):
            bpy.types.SpaceView3D.draw_handler_remove(self._handle, 'WINDOW')
            self._handle = None

        if not self.path:
            return

        # --- [수정됨] 클릭 판별 로직 추가 ---
        # 시작점과 마지막 점(현재 마우스 위치)의 거리가 짧거나, 경로 점이 너무 적으면 클릭 처리
        start_pos = self.path[0]
        end_pos = self.path[-1]
        drag_distance = (end_pos - start_pos).length
        
        # 점이 3개 미만이거나 드래그 거리가 5픽셀 미만인 경우
        if len(self.path) < 3 or drag_distance < 5.0:
            bpy.ops.view3d.select(
                extend=event.shift,
                deselect=event.ctrl,
                toggle=event.shift,
                location=(int(event.mouse_region_x), int(event.mouse_region_y))
            )
            return
        # -----------------------------------

        # 1. 모드 확인
        sel_mode = 'SET'
        if event.shift and not event.ctrl:
            sel_mode = 'ADD'
        elif event.ctrl and not event.shift:
            sel_mode = 'SUB'
        elif event.ctrl and event.shift:
            sel_mode = 'ADD'

        # 2. 수동 선택 로직
        region = context.region
        rv3d = context.space_data.region_3d
        
        candidates = [o for o in context.view_layer.objects if o.visible_get() and not o.hide_select]
        poly_points = [(p.x, p.y) for p in self.path]

        for obj in candidates:
            loc_3d = obj.matrix_world.translation
            loc_2d = view3d_utils.location_3d_to_region_2d(region, rv3d, loc_3d)

            if loc_2d is None:
                continue

            is_inside = is_point_in_polygon((loc_2d.x, loc_2d.y), poly_points)

            if sel_mode == 'SET':
                obj.select_set(is_inside)
            elif sel_mode == 'ADD':
                if is_inside: obj.select_set(True)
            elif sel_mode == 'SUB':
                if is_inside: obj.select_set(False)

        # 3. 가장 가까운 오브젝트 Active 설정
        if self.path:
            find_closest_and_set_active(context, self.path[-1])

    def cancel(self, context):
        if getattr(self, '_handle', None):
            bpy.types.SpaceView3D.draw_handler_remove(self._handle, 'WINDOW')
            self._handle = None
        context.area.tag_redraw()

    def draw_callback_px(self, context):
        is_dragging = getattr(self, 'is_dragging', False)
        if not is_dragging or len(self.path) < 2:
            return

        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        vertices = [ (p.x, p.y) for p in self.path ]
        
        # --- 1. 내부 채우기 (Fill) ---
        batch_fill = batch_for_shader(shader, 'TRI_FAN', {"pos": vertices})

        gpu.state.blend_set('ALPHA')
        shader.bind()
        
        # 반투명 회색 설정
        shader.uniform_float("color", (0.8, 0.8, 0.8, 0.1))
        batch_fill.draw(shader)
        
        # --- 2. 외곽선 그리기 (Outline) ---
        batch_outline = batch_for_shader(shader, 'LINE_LOOP', {"pos": vertices})

        # 흰색 실선
        shader.uniform_float("color", (1.0, 1.0, 1.0, 0.6))
        batch_outline.draw(shader)
        
        gpu.state.blend_set('NONE')


# =========================================================================
# 3. Tool Classes
# =========================================================================
class VIEW3D_WST_smart_box_select(bpy.types.WorkSpaceTool):
    bl_space_type = 'VIEW_3D'
    bl_context_mode = 'OBJECT'
    bl_idname = "my_tool.smart_box_select"
    bl_label = "Smart Box Select"
    bl_description = "Box select. Short click selects single object."
    bl_icon = "ops.generic.select_box"
    bl_keymap = (
        ("view3d.smart_box_select", {"type": 'LEFTMOUSE', "value": 'PRESS'}, None),
        ("view3d.smart_box_select", {"type": 'LEFTMOUSE', "value": 'PRESS', "shift": True}, None),
        ("view3d.smart_box_select", {"type": 'LEFTMOUSE', "value": 'PRESS', "ctrl": True}, None),
        ("view3d.smart_box_select", {"type": 'LEFTMOUSE', "value": 'PRESS', "shift": True, "ctrl": True}, None),
    )
    bl_widget = None

class VIEW3D_WST_smart_lasso_select(bpy.types.WorkSpaceTool):
    bl_space_type = 'VIEW_3D'
    bl_context_mode = 'OBJECT'
    bl_idname = "my_tool.smart_lasso_select"
    bl_label = "Smart Lasso Select"
    bl_description = "Lasso select. Short click selects single object."
    bl_icon = "ops.generic.select_lasso"
    bl_keymap = (
        ("view3d.smart_lasso_select", {"type": 'LEFTMOUSE', "value": 'PRESS'}, None),
        ("view3d.smart_lasso_select", {"type": 'LEFTMOUSE', "value": 'PRESS', "shift": True}, None),
        ("view3d.smart_lasso_select", {"type": 'LEFTMOUSE', "value": 'PRESS', "ctrl": True}, None),
        ("view3d.smart_lasso_select", {"type": 'LEFTMOUSE', "value": 'PRESS', "shift": True, "ctrl": True}, None),
    )
    bl_widget = None


# =========================================================================
# 4. Registration
# =========================================================================
classes = (
    VIEW3D_OT_smart_box_select,
    VIEW3D_OT_smart_lasso_select,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    
    bpy.utils.register_tool(VIEW3D_WST_smart_box_select, separator=True, group=True)
    bpy.utils.register_tool(VIEW3D_WST_smart_lasso_select, after={VIEW3D_WST_smart_box_select.bl_idname})

def unregister():
    bpy.utils.unregister_tool(VIEW3D_WST_smart_lasso_select)
    bpy.utils.unregister_tool(VIEW3D_WST_smart_box_select)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

if __name__ == "__main__":
    register()
