import bpy


class VIEW3D_PT_helper_mesh_panel(bpy.types.Panel):
    """Creates a Panel in the 3D viewport N-panel"""

    bl_label = "Gauss Cannon: Gaussian Splatting Toolbox"
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
        row.label(text="Helper Meshes", icon="MESH_DATA")
        row.label(text=f"({len(scene.helper_meshes)} total)")

        row = box.row()
        row.operator("mesh.add_helper", icon="ADD")
        row.operator("mesh.clear_helpers", icon="X")

        # List of helper meshes
        if len(scene.helper_meshes) > 0:
            col = box.column()
            for i, item in enumerate(scene.helper_meshes):
                row = col.row(align=True)

                # Show mesh status
                # Check if mesh_object is a valid Blender object (not a deferred property)
                if item.mesh_object is None:
                    row.label(text=f"{item.name} (Missing)", icon="ERROR")
                else:
                    try:
                        # Try to access the object properties
                        obj_type = item.mesh_object.type
                        if obj_type == 'MESH' and item.mesh_object.data:
                            icon = "MESH_DATA" if item.mesh_object.visible_get() else "HIDE_ON"
                            face_count = len(item.mesh_object.data.polygons)
                            row.label(text=f"{item.name} ({face_count} faces)", icon=icon)
                        else:
                            row.label(text=f"{item.name} (Not a mesh)", icon="ERROR")
                    except (AttributeError, ReferenceError):
                        # Handle case where mesh_object is deferred or deleted
                        row.label(text=f"{item.name} (Not loaded)", icon="ERROR")

                op = row.operator("mesh.remove_helper", text="", icon="X")
                op.index = i
        else:
            box.label(text="No helper meshes added")
            box.label(text="Select meshes and click '+'", icon="INFO")

        # Camera settings
        box = layout.box()
        box.label(text="Camera Settings", icon="CAMERA_DATA")

        col = box.column(align=True)
        col.prop(scene, "camera_focal_length")

        row = col.row(align=True)
        row.prop(scene, "output_width")
        row.prop(scene, "output_height")

        col.prop(scene, "skip_interior_cameras")

        # Export settings
        box = layout.box()
        box.label(text="Export Settings", icon="EXPORT")

        col = box.column()
        col.prop(scene, "json_output_path")
        col.prop(scene, "export_mode")
        col.prop(scene, "coordinate_system")

        # Action buttons
        layout.separator()

        # Show total face count
        total_faces = 0
        for item in scene.helper_meshes:
            try:
                if item.mesh_object and item.mesh_object.type == 'MESH' and item.mesh_object.data:
                    total_faces += len(item.mesh_object.data.polygons)
            except (AttributeError, ReferenceError):
                # Skip items with deferred or invalid mesh objects
                pass
        if total_faces > 0:
            layout.label(text=f"Total faces: {total_faces}", icon="INFO")

        col = layout.column(align=True)
        col.scale_y = 1.5
        col.operator("camera.generate_from_faces", icon="CAMERA_DATA")
        col.operator("export.camera_json", icon="EXPORT")

        layout.separator()

        row = layout.row()
        row.scale_y = 2.0
        row.operator("camera.generate_and_export", icon="FILE_REFRESH")

        # Point cloud generation
        layout.separator()

        box = layout.box()
        box.label(text="Point Cloud Export", icon="MESH_DATA")

        # Warning about performance and beta status
        warning_box = box.box()
        warning_box.alert = True
        warning_box.label(text="BETA: Be patient, slow.", icon="ERROR")

        # Show selected objects count
        selected_meshes = [
            obj for obj in context.selected_objects if obj.type == "MESH"
        ]
        if selected_meshes:
            box.label(text=f"Selected objects: {len(selected_meshes)}", icon="INFO")
        else:
            box.label(text="No mesh objects selected", icon="ERROR")

        col = box.column()
        col.prop(scene, "pointcloud_output_path")
        col.prop(scene, "pointcloud_resolution")
        col.prop(scene, "use_gpu_acceleration")

        col.separator()
        col.scale_y = 1.5
        col.operator("export.pointcloud_ply", icon="EXPORT")