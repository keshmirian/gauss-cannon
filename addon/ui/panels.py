import bpy


VERSION = "1.0.1"


class VIEW3D_PT_helper_mesh_panel(bpy.types.Panel):
    """Creates a Panel in the 3D viewport N-panel"""

    bl_label = "Gauss Cannon"
    bl_idname = "VIEW3D_PT_helper_mesh_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Gauss Cannon"

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        # Helper mesh section
        box = layout.box()
        row = box.row()
        row.label(text="Helper Meshes", icon="OUTLINER_OB_MESH")
        if len(scene.helper_meshes) > 0:
            # Show total face count inline
            total_faces = 0
            for item in scene.helper_meshes:
                try:
                    if item.mesh_object and item.mesh_object.type == 'MESH' and item.mesh_object.data:
                        total_faces += len(item.mesh_object.data.polygons)
                except (AttributeError, ReferenceError):
                    pass
            row.label(text=f"{len(scene.helper_meshes)} meshes, {total_faces} faces")

        row = box.row(align=True)
        row.operator("mesh.add_helper", text="Add Selected", icon="ADD")
        row.operator("mesh.clear_helpers", text="Clear All", icon="TRASH")

        # List of helper meshes
        if len(scene.helper_meshes) > 0:
            col = box.column(align=True)
            for i, item in enumerate(scene.helper_meshes):
                row = col.row(align=True)

                if item.mesh_object is None:
                    row.label(text=f"{item.name} (Missing)", icon="ERROR")
                else:
                    try:
                        obj_type = item.mesh_object.type
                        if obj_type == 'MESH' and item.mesh_object.data:
                            icon = "OUTLINER_OB_MESH" if item.mesh_object.visible_get() else "HIDE_ON"
                            face_count = len(item.mesh_object.data.polygons)
                            row.label(text=f"{item.name} ({face_count})", icon=icon)
                        else:
                            row.label(text=f"{item.name} (Invalid)", icon="ERROR")
                    except (AttributeError, ReferenceError):
                        row.label(text=f"{item.name} (Not loaded)", icon="ERROR")

                op = row.operator("mesh.remove_helper", text="", icon="X")
                op.index = i
        else:
            col = box.column()
            col.label(text="No helper meshes added")
            col.label(text="Select mesh objects and click 'Add Selected'", icon="INFO")

        # Camera generation section
        box = layout.box()
        box.label(text="Camera Generation", icon="CAMERA_DATA")

        col = box.column(align=True)
        col.prop(scene, "camera_focal_length")
        row = col.row(align=True)
        row.prop(scene, "output_width")
        row.prop(scene, "output_height")
        col.prop(scene, "skip_interior_cameras")

        col.separator()
        col.scale_y = 1.3
        col.operator("camera.generate_from_faces", text="Generate Cameras", icon="CAMERA_DATA")

        # Export section
        box = layout.box()
        box.label(text="Camera Export", icon="EXPORT")

        col = box.column(align=True)
        col.prop(scene, "json_output_path")
        col.prop(scene, "export_mode")
        col.prop(scene, "coordinate_system")

        col.separator()
        col.scale_y = 1.3
        col.operator("export.camera_json", text="Export Camera JSON", icon="FILE_TEXT")

        # Combined action
        layout.separator()
        row = layout.row()
        row.scale_y = 1.8
        row.operator("camera.generate_and_export", text="Generate & Export All", icon="FILE_REFRESH")

        # Point cloud section
        layout.separator()
        box = layout.box()
        box.label(text="Point Cloud", icon="OUTLINER_OB_POINTCLOUD")

        # Show selected objects count
        selected_meshes = [
            obj for obj in context.selected_objects if obj.type == "MESH"
        ]
        if selected_meshes:
            box.label(text=f"{len(selected_meshes)} mesh(es) selected", icon="CHECKMARK")
        else:
            box.label(text="Select mesh objects to scan", icon="INFO")

        col = box.column(align=True)
        col.prop(scene, "pointcloud_output_path")
        col.prop(scene, "pointcloud_resolution")
        col.prop(scene, "use_gpu_acceleration")

        col.separator()
        col.scale_y = 1.3
        col.operator("export.pointcloud_ply", text="Generate Point Cloud", icon="OUTLINER_OB_POINTCLOUD")

        # Footer with version
        layout.separator()
        row = layout.row()
        row.alignment = 'RIGHT'
        row.scale_y = 0.7
        row.label(text=f"v{VERSION}")