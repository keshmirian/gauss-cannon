# SPDX-License-Identifier: GPL-3.0-or-later

import bpy
from bpy.types import Operator, Panel

class HELLO_OT_world(Operator):
    """Hello World Operator"""
    bl_idname = "hello.world"
    bl_label = "Say Hello"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        # Print to console and show popup
        print("Hello World from Blender 4.2!")
        self.report({'INFO'}, "Hello World from the new extension system!")
        
        # Optional: Create a simple cube as a demonstration
        bpy.ops.mesh.primitive_cube_add(location=(0, 0, 2))
        context.active_object.name = "Hello_Cube"
        
        return {'FINISHED'}

class HELLO_PT_panel(Panel):
    """Hello World Panel"""
    bl_label = "Hello World"
    bl_idname = "HELLO_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Hello" 
    
    def draw(self, context):
        layout = self.layout
        layout.operator("hello.world", text="Say Hooloo & Add Cube")
        
        # Add some additional UI elements
        layout.separator()
        layout.label(text="Blender 4.2+ Extension!")
        
        row = layout.row()
        row.label(text="Version: 1.0.0")

# Registration
classes = [
    HELLO_OT_world,
    HELLO_PT_panel,
]

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in classes:
        bpy.utils.unregister_class(cls)