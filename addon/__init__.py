import bpy

# Import property classes and registration functions
from .properties import HelperMeshItem, register_properties, unregister_properties

# Import all operators
from .operators import (
    MESH_OT_add_helper,
    MESH_OT_remove_helper,
    MESH_OT_clear_helpers,
    CAMERA_OT_generate_from_faces,
    CAMERA_OT_generate_and_export,
    EXPORT_OT_camera_json,
    EXPORT_OT_pointcloud_ply,
)

# Import UI panels
from .ui import VIEW3D_PT_helper_mesh_panel

# Classes to register
classes = [
    # Property groups
    HelperMeshItem,

    # Operators
    MESH_OT_add_helper,
    MESH_OT_remove_helper,
    MESH_OT_clear_helpers,
    CAMERA_OT_generate_from_faces,
    CAMERA_OT_generate_and_export,
    EXPORT_OT_camera_json,
    EXPORT_OT_pointcloud_ply,

    # UI panels
    VIEW3D_PT_helper_mesh_panel,
]


def register():
    """Register all addon classes and properties"""
    # Register all classes
    for cls in classes:
        bpy.utils.register_class(cls)

    # Register scene properties
    register_properties()


def unregister():
    """Unregister all addon classes and properties"""
    # Unregister scene properties first
    unregister_properties()

    # Unregister all classes in reverse order
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()