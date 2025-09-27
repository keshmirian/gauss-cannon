import bpy


class MESH_OT_add_helper(bpy.types.Operator):
    """Add selected mesh as helper object"""

    bl_idname = "mesh.add_helper"
    bl_label = "Add Selected Mesh"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.selected_objects and any(
            obj.type == "MESH" for obj in context.selected_objects
        )

    def execute(self, context):
        scene = context.scene
        added_count = 0

        for obj in context.selected_objects:
            if obj.type == "MESH":
                # Check if already in list
                exists = False
                for item in scene.helper_meshes:
                    try:
                        if item.mesh_object == obj:
                            exists = True
                            break
                    except (AttributeError, ReferenceError):
                        pass
                if not exists:
                    item = scene.helper_meshes.add()
                    item.mesh_object = obj
                    item.name = obj.name
                    # Hide from render
                    obj.hide_render = True
                    added_count += 1

        self.report({"INFO"}, f"Added {added_count} helper mesh(es)")
        return {"FINISHED"}


class MESH_OT_remove_helper(bpy.types.Operator):
    """Remove helper mesh from list"""

    bl_idname = "mesh.remove_helper"
    bl_label = "Remove Helper Mesh"
    bl_options = {"REGISTER", "UNDO"}

    index: bpy.props.IntProperty()

    def execute(self, context):
        scene = context.scene

        if 0 <= self.index < len(scene.helper_meshes):
            # Re-enable rendering for the mesh
            helper_item = scene.helper_meshes[self.index]
            try:
                if helper_item.mesh_object:
                    helper_item.mesh_object.hide_render = False
            except (AttributeError, ReferenceError):
                pass

            scene.helper_meshes.remove(self.index)
            scene.helper_mesh_index = min(
                max(0, scene.helper_mesh_index - 1), len(scene.helper_meshes) - 1
            )

        return {"FINISHED"}


class MESH_OT_clear_helpers(bpy.types.Operator):
    """Clear all helper meshes"""

    bl_idname = "mesh.clear_helpers"
    bl_label = "Clear All"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene

        # Re-enable rendering for all meshes
        for item in scene.helper_meshes:
            try:
                if item.mesh_object:
                    item.mesh_object.hide_render = False
            except (AttributeError, ReferenceError):
                pass

        scene.helper_meshes.clear()
        scene.helper_mesh_index = 0

        return {"FINISHED"}