import bpy
import os
import json
import math
import mathutils
from mathutils import Vector, Matrix
import numpy as np

# Property group to store helper mesh reference
class HelperMeshItem(bpy.types.PropertyGroup):
    mesh_object: bpy.props.PointerProperty(
        name="Mesh Object",
        type=bpy.types.Object,
        poll=lambda self, obj: obj.type == 'MESH'
    )
    name: bpy.props.StringProperty(name="Name")

# Add helper mesh operator
class MESH_OT_add_helper(bpy.types.Operator):
    """Add selected mesh as helper object"""
    bl_idname = "mesh.add_helper"
    bl_label = "Add Selected Mesh"
    bl_options = {'REGISTER', 'UNDO'}
    
    @classmethod
    def poll(cls, context):
        return context.selected_objects and any(obj.type == 'MESH' for obj in context.selected_objects)
    
    def execute(self, context):
        scene = context.scene
        
        for obj in context.selected_objects:
            if obj.type == 'MESH':
                # Check if already in list
                exists = any(item.mesh_object == obj for item in scene.helper_meshes)
                if not exists:
                    item = scene.helper_meshes.add()
                    item.mesh_object = obj
                    item.name = obj.name
                    # Hide from render
                    obj.hide_render = True
        
        return {'FINISHED'}

# Remove helper mesh operator
class MESH_OT_remove_helper(bpy.types.Operator):
    """Remove helper mesh from list"""
    bl_idname = "mesh.remove_helper"
    bl_label = "Remove Helper Mesh"
    bl_options = {'REGISTER', 'UNDO'}
    
    index: bpy.props.IntProperty()
    
    def execute(self, context):
        scene = context.scene
        
        if 0 <= self.index < len(scene.helper_meshes):
            # Re-enable rendering for the mesh
            helper_item = scene.helper_meshes[self.index]
            if helper_item.mesh_object:
                helper_item.mesh_object.hide_render = False
            
            scene.helper_meshes.remove(self.index)
            scene.helper_mesh_index = min(max(0, scene.helper_mesh_index - 1), len(scene.helper_meshes) - 1)
        
        return {'FINISHED'}

# Clear all helper meshes operator
class MESH_OT_clear_helpers(bpy.types.Operator):
    """Clear all helper meshes"""
    bl_idname = "mesh.clear_helpers"
    bl_label = "Clear All"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        scene = context.scene
        
        # Re-enable rendering for all meshes
        for item in scene.helper_meshes:
            if item.mesh_object:
                item.mesh_object.hide_render = False
        
        scene.helper_meshes.clear()
        scene.helper_mesh_index = 0
        
        return {'FINISHED'}

# Generate camera keyframes operator
class CAMERA_OT_generate_from_faces(bpy.types.Operator):
    """Generate camera keyframes from helper mesh faces"""
    bl_idname = "camera.generate_from_faces"
    bl_label = "Generate Camera Keyframes"
    bl_options = {'REGISTER', 'UNDO'}
    
    @classmethod
    def poll(cls, context):
        return len(context.scene.helper_meshes) > 0
    
    def execute(self, context):
        scene = context.scene
        
        # Get or create camera
        camera = scene.camera
        if not camera:
            bpy.ops.object.camera_add()
            camera = context.active_object
            scene.camera = camera
        
        # Set camera properties
        camera.data.lens = scene.custom_focal_length
        
        # Clear existing keyframes
        camera.animation_data_clear()
        
        frame_num = 1
        
        # Process each helper mesh
        for helper_item in scene.helper_meshes:
            mesh_obj = helper_item.mesh_object
            if not mesh_obj or mesh_obj.type != 'MESH':
                continue
            
            # Get evaluated mesh (with modifiers applied)
            depsgraph = context.evaluated_depsgraph_get()
            mesh_eval = mesh_obj.evaluated_get(depsgraph)
            mesh = mesh_eval.to_mesh()
            
            # Get world matrix
            world_matrix = mesh_obj.matrix_world
            
            # Process each face
            for poly in mesh.polygons:
                # Calculate face center in world space
                face_center = Vector((0, 0, 0))
                for vert_idx in poly.vertices:
                    face_center += mesh.vertices[vert_idx].co
                face_center /= len(poly.vertices)
                face_center = world_matrix @ face_center
                
                # Get face normal in world space (pointing opposite)
                face_normal = world_matrix.to_3x3() @ poly.normal
                face_normal.normalize()
                face_normal = -face_normal  # Point opposite to face normal
                
                # Calculate camera orientation
                # Forward is opposite of face normal
                forward = face_normal
                
                # Calculate up vector (prefer world Z up)
                world_up = Vector((0, 0, 1))
                right = forward.cross(world_up)
                
                # Handle case where forward is parallel to world up
                if right.length < 0.001:
                    world_up = Vector((0, 1, 0))
                    right = forward.cross(world_up)
                
                right.normalize()
                up = right.cross(forward)
                up.normalize()
                
                # Create rotation matrix
                rot_matrix = Matrix((
                    right,
                    up,
                    -forward  # Camera looks down negative Z
                )).transposed()
                
                # Set camera transform
                camera.location = face_center
                camera.rotation_euler = rot_matrix.to_euler()
                
                # Insert keyframes
                camera.keyframe_insert(data_path="location", frame=frame_num)
                camera.keyframe_insert(data_path="rotation_euler", frame=frame_num)
                
                frame_num += 1
            
            # Clean up evaluated mesh
            mesh_eval.to_mesh_clear()
        
        # Set frame range
        scene.frame_start = 1
        scene.frame_end = frame_num - 1
        
        # Set render resolution
        scene.render.resolution_x = scene.resolution_x
        scene.render.resolution_y = scene.resolution_y
        
        self.report({'INFO'}, f"Generated {frame_num - 1} camera keyframes")
        return {'FINISHED'}

# Export camera JSON operator
class EXPORT_OT_camera_json(bpy.types.Operator):
    """Export camera parameters to JSON"""
    bl_idname = "export.camera_json"
    bl_label = "Export Camera JSON"
    bl_options = {'REGISTER', 'UNDO'}
    
    @classmethod
    def poll(cls, context):
        return context.scene.camera and context.scene.frame_end > context.scene.frame_start
    
    def calculate_scene_bounding_box(self):
        min_x, min_y, min_z = float('inf'), float('inf'), float('inf')
        max_x, max_y, max_z = float('-inf'), float('-inf'), float('-inf')
        
        for obj in bpy.context.view_layer.objects:
            if obj.type == 'MESH' and not obj.hide_render:
                for vert in obj.bound_box:
                    co_world = obj.matrix_world @ Vector(vert[:])
                    min_x = min(min_x, co_world.x)
                    max_x = max(max_x, co_world.x)
                    min_y = min(min_y, co_world.y)
                    max_y = max(max_y, co_world.y)
                    min_z = min(min_z, co_world.z)
                    max_z = max(max_z, co_world.z)
        
        dimensions = (max_x - min_x, max_y - min_y, max_z - min_z)
        return max(dimensions)
    
    def get_camera_data(self, camera, scene):
        lens = camera.data.lens
        sensor_width = camera.data.sensor_width
        sensor_height = camera.data.sensor_height
        
        render_width_px = scene.render.resolution_x
        render_height_px = scene.render.resolution_y
        
        # Calculate focal length in pixels
        focal_length_x_px = (lens * render_width_px) / sensor_width
        focal_length_y_px = (lens * render_height_px) / sensor_height
        
        # Calculate field of view
        camera_angle_x = 2 * math.atan(sensor_width / (2 * lens))
        camera_angle_y = 2 * math.atan(sensor_height / (2 * lens))
        
        # Get transformation matrix
        transform_matrix = camera.matrix_world
        
        return {
            "fl_x": focal_length_x_px,
            "fl_y": focal_length_y_px,
            "camera_angle_x": camera_angle_x,
            "camera_angle_y": camera_angle_y,
            "transform_matrix": [list(row) for row in transform_matrix]
        }
    
    def execute(self, context):
        scene = context.scene
        camera = scene.camera
        
        if not camera:
            self.report({'ERROR'}, "No camera found in scene")
            return {'CANCELLED'}
        
        # Calculate AABB scale
        aabb_scale = self.calculate_scene_bounding_box()
        
        # Get camera data for first frame
        scene.frame_set(scene.frame_start)
        cam_data = self.get_camera_data(camera, scene)
        
        # Prepare output data structure
        output_data = {
            "aabb_scale": aabb_scale,
            "w": scene.render.resolution_x,
            "h": scene.render.resolution_y,
            "camera_angle_x": cam_data["camera_angle_x"],
            "camera_angle_y": cam_data["camera_angle_y"],
            "frames": []
        }
        
        # Add focal length for non-Instant-NGP/Postshot modes
        if not (scene.optimize_postshot):
            output_data["fl_x"] = cam_data["fl_x"]
            output_data["fl_y"] = cam_data["fl_y"]
        
        # Add center point for test data
        output_data["cx"] = scene.render.resolution_x / 2
        output_data["cy"] = scene.render.resolution_y / 2
        
        # Process each frame
        for frame in range(scene.frame_start, scene.frame_end + 1):
            scene.frame_set(frame)
            cam_data = self.get_camera_data(camera, scene)
            
            frame_data = {
                "transform_matrix": cam_data["transform_matrix"],
                "file_path": f"images\\{frame:04d}"
            }
            
            # Add per-frame camera parameters for non-optimized modes
            if not (scene.optimize_postshot):
                frame_data.update({
                    "w": scene.render.resolution_x,
                    "h": scene.render.resolution_y,
                    "fl_x": cam_data["fl_x"],
                    "fl_y": cam_data["fl_y"],
                    "camera_angle_x": cam_data["camera_angle_x"],
                    "camera_angle_y": cam_data["camera_angle_y"]
                })
            
            output_data["frames"].append(frame_data)
        
        # Write JSON file
        output_path = bpy.path.abspath(scene.export_path)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        with open(output_path, 'w') as f:
            json.dump(output_data, f, indent=4)
        
        self.report({'INFO'}, f"Exported camera data to {output_path}")
        return {'FINISHED'}

# Combined generate and export operator
class CAMERA_OT_generate_and_export(bpy.types.Operator):
    """Generate camera keyframes and export JSON"""
    bl_idname = "camera.generate_and_export"
    bl_label = "Generate & Export"
    bl_options = {'REGISTER', 'UNDO'}
    
    @classmethod
    def poll(cls, context):
        return len(context.scene.helper_meshes) > 0
    
    def execute(self, context):
        # Generate keyframes
        bpy.ops.camera.generate_from_faces()
        # Export JSON
        bpy.ops.export.camera_json()
        return {'FINISHED'}

# UI Panel
class VIEW3D_PT_helper_mesh_panel(bpy.types.Panel):
    """Creates a Panel in the 3D viewport N-panel"""
    bl_label = "Face Camera Generator"
    bl_idname = "VIEW3D_PT_helper_mesh_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Face Camera"
    
    def draw(self, context):
        layout = self.layout
        scene = context.scene
        
        # Helper mesh section
        box = layout.box()
        box.label(text="Helper Meshes", icon='MESH_DATA')
        
        row = box.row()
        row.operator("mesh.add_helper", icon='ADD')
        row.operator("mesh.clear_helpers", icon='X')
        
        # List of helper meshes
        if len(scene.helper_meshes) > 0:
            col = box.column()
            for i, item in enumerate(scene.helper_meshes):
                row = col.row(align=True)
                if item.mesh_object:
                    row.label(text=item.name, icon='MESH_DATA')
                else:
                    row.label(text="(Missing)", icon='ERROR')
                op = row.operator("mesh.remove_helper", text="", icon='X')
                op.index = i
        else:
            box.label(text="No helper meshes added")
        
        # Export settings
        box = layout.box()
        box.label(text="Export Settings", icon='EXPORT')
        
        col = box.column()
        col.prop(scene, "export_path")
        
        row = col.row(align=True)
        row.prop(scene, "resolution_x")
        row.prop(scene, "resolution_y")

        col.prop(scene, "custom_focal_length")
        
        col.prop(scene, "optimize_postshot")
        
        # Action buttons
        layout.separator()
        col = layout.column()
        col.operator("camera.generate_from_faces", icon='CAMERA_DATA')
        col.operator("export.camera_json", icon='EXPORT')
        col.operator("camera.generate_and_export", icon='FILE_REFRESH')

# Registration
classes = [
    HelperMeshItem,
    MESH_OT_add_helper,
    MESH_OT_remove_helper,
    MESH_OT_clear_helpers,
    CAMERA_OT_generate_from_faces,
    EXPORT_OT_camera_json,
    CAMERA_OT_generate_and_export,
    VIEW3D_PT_helper_mesh_panel,
]

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    
    # Add properties to scene
    bpy.types.Scene.helper_meshes = bpy.props.CollectionProperty(type=HelperMeshItem)
    bpy.types.Scene.helper_mesh_index = bpy.props.IntProperty(default=0)
    
    bpy.types.Scene.export_path = bpy.props.StringProperty(
        name="Export Path",
        description="Path to export camera JSON file",
        default="//camera_data.json",
        subtype='FILE_PATH'
    )
    
    bpy.types.Scene.resolution_x = bpy.props.IntProperty(
        name="Resolution X",
        description="Horizontal resolution",
        default=1920,
        min=1,
        max=10000
    )
    
    bpy.types.Scene.resolution_y = bpy.props.IntProperty(
        name="Resolution Y",
        description="Vertical resolution",
        default=1080,
        min=1,
        max=10000
    )
    
    bpy.types.Scene.custom_focal_length = bpy.props.FloatProperty(
        name="Focal Length",
        description="Camera focal length in mm",
        default=35.0,
        min=1.0,
        max=500.0
    )
    
    bpy.types.Scene.optimize_postshot = bpy.props.BoolProperty(
        name="Optimize for Postshot",
        description="Adjust export parameters for Postshot compatibility",
        default=False
    )

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    
    # Remove properties
    del bpy.types.Scene.helper_meshes
    del bpy.types.Scene.helper_mesh_index
    del bpy.types.Scene.export_path
    del bpy.types.Scene.resolution_x
    del bpy.types.Scene.resolution_y
    del bpy.types.Scene.custom_focal_length
    del bpy.types.Scene.optimize_postshot

if __name__ == "__main__":
    register()