"""Physical workstation detail authored in the room's existing Godot coordinates.

The live display aperture stays at (-.25, 1.10, -2.36), 1.15 x .65 meters.
There is no baked display face. The back shell sits behind that plane. Keyboard
legends are small real font meshes, readable in close inspection rather than
texture-dependent decoration. No downloaded assets or fonts are required.
"""
import math


def build_monitor(a, box, cyl, rod, text):
    a.activate("monitor", "Walnut monitor", (-.25, .7825, -2.36),
               "computer_monitor", parent_id="desk", library=True)
    for side, x in (("left", -.845), ("right", .345)):
        box("Display " + side + " walnut bezel", (x, 1.10, -2.398),
            (.035, .705, .09), "WalnutDeep", .008, role="monitor_bezel")
    for side, y in (("bottom", .754), ("top", 1.446)):
        box("Display " + side + " walnut bezel", (-.25, y, -2.398),
            (1.224, .035, .09), "WalnutDeep", .008, role="monitor_bezel")
    box("Display rear shell", (-.25, 1.10, -2.455),
        (1.16, .642, .022), "BlackSteel", .015, role="monitor_back_panel")
    box("Display rear service cover", (-.25, 1.075, -2.474),
        (.40, .32, .017), "WalnutDeep", .012, role="monitor_service_panel")
    for index in range(18):
        x = -.73 + index * .056
        box("Display cooling vent " + str(index + 1), (x, 1.373, -2.469),
            (.031, .010, .007), "Ink", .002, role="monitor_vent")
    for x in (-.40, -.10):
        for y in (.965, 1.185):
            cyl("Display service fastener", (x, y, -2.486), .005, .003,
                "BrassAged", 12, (math.pi / 2, 0, 0), role="fastener")
    box("Display input recess", (-.04, .841, -2.476),
        (.17, .026, .009), "Ink", .003, role="monitor_port_recess")
    for index, x in enumerate((-.09, -.035, .015)):
        box("Display input socket " + str(index + 1), (x, .842, -2.482),
            (.033, .011, .004), "BrassAged", .001, role="monitor_port")
    box("Display brass footing", (-.25, .808, -2.59),
        (.36, .022, .22), "BrassAged", .014, role="monitor_stand_base")
    box("Display stand rubber sole", (-.25, .794, -2.59),
        (.30, .006, .17), "Ink", .003, role="monitor_stand_pad")
    rod("Display stand upright", (-.25, .819, -2.57), (-.25, 1.085, -2.493),
        .025, "BlackSteel", role="monitor_stand")
    cyl("Display tilt hinge", (-.25, 1.085, -2.491), .038, .17,
        "BrassAged", 24, (0, math.pi / 2, 0), role="monitor_hinge")
    for x in (.257, .289):
        cyl("Display underside control", (x, .739, -2.410), .006, .006,
            "BlackSteel", 12, role="monitor_control")
    a.anchor("desk_screen", (-.25, 1.10, -2.36), size=[1.15, .65],
             width=1.15, height=.65, semantic_role="live_desktop_surface",
             normal=[0, 0, 1])


def build_keyboard(a, box, text):
    a.activate("keyboard", "Ivory mechanical keyboard", (-.20, .792, -2.098),
               "keyboard", parent_id="desk", library=True)
    box("Keyboard lower chassis", (-.20, .803, -2.098),
        (.548, .022, .177), "BlackSteel", .008, role="keyboard_chassis")
    box("Keyboard brass switch plate", (-.20, .816, -2.098),
        (.526, .006, .158), "BrassAged", .003, role="keyboard_switch_plate")
    # A compact 60% layout. Each tuple is (legend, width in key units).
    rows = [
        [("Esc", 1), ("1", 1), ("2", 1), ("3", 1), ("4", 1), ("5", 1),
         ("6", 1), ("7", 1), ("8", 1), ("9", 1), ("0", 1), ("-", 1), ("=", 1), ("Bksp", 2)],
        [("Tab", 1.5), ("Q", 1), ("W", 1), ("E", 1), ("R", 1), ("T", 1),
         ("Y", 1), ("U", 1), ("I", 1), ("O", 1), ("P", 1), ("[", 1), ("]", 1), ("\\", 1.5)],
        [("Caps", 1.75), ("A", 1), ("S", 1), ("D", 1), ("F", 1), ("G", 1),
         ("H", 1), ("J", 1), ("K", 1), ("L", 1), (";", 1), ("'", 1), ("Enter", 2.25)],
        [("Shift", 2.25), ("Z", 1), ("X", 1), ("C", 1), ("V", 1), ("B", 1),
         ("N", 1), ("M", 1), (",", 1), (".", 1), ("/", 1), ("Shift", 2.75)],
        [("Ctrl", 1.25), ("Meta", 1.25), ("Alt", 1.25), ("", 6.25),
         ("Alt", 1.25), ("Fn", 1.25), ("Menu", 1.25), ("Ctrl", 1.25)],
    ]
    unit, gap = .0346, .0042
    for row_index, row in enumerate(rows):
        cursor = -.20 - 15 * unit / 2
        z = -2.160 + row_index * .031
        for key_index, (legend, units) in enumerate(row):
            key_id = "r" + str(row_index + 1) + "-k" + str(key_index + 1).zfill(2)
            width = units * unit - gap
            x = cursor + units * unit / 2
            cursor += units * unit
            box("Keyboard keycap " + (legend or "Space"), (x, .826, z),
                (width, .014, .026), "Bone", .003, part_id=key_id + "-cap",
                role="keyboard_keycap")
            if legend:
                glyph = text("Keyboard legend " + legend, legend, (x, .8334, z + .0038),
                             .0064 if len(legend) > 1 else .0092, "Ink",
                             rotation=(0, 0, 0), part_id=key_id + "-legend",
                             role="keyboard_legend")
                glyph.data.extrude = 0
                glyph.data.bevel_depth = 0
                glyph.data.resolution_u = 2
            if legend in ("F", "J"):
                box("Keyboard tactile home marker " + legend, (x, .834, z + .009),
                    (.009, .0012, .0013), "Bone", .0003,
                    role="keyboard_tactile_marker")
    for x in (-.43, .03):
        for z in (-2.164, -2.03):
            box("Keyboard rubber foot", (x, .790, z), (.032, .004, .023),
                "Ink", .002, role="keyboard_foot")
    box("Keyboard rear USB C recess", (-.39, .807, -2.188),
        (.018, .006, .004), "Ink", .002, role="keyboard_port")
    a.anchor("keyboard", (-.20, .834, -2.098), size=[.548, .177],
             semantic_role="physical_keyboard", normal=[0, 1, 0])


def build_computer(a, box, cyl, text):
    a.activate("computer", "Compact Hermes workstation", (.60, .7825, -2.80),
               "computer", parent_id="desk", library=True)
    # Separate panels surround a smaller dark chassis. The narrow reveals are
    # intentional seams; no fake giant box masquerades as the entire machine.
    box("Computer internal chassis", (.60, .902, -2.80), (.220, .188, .286),
        "Ink", .004, role="computer_chassis")
    box("Computer walnut top panel", (.60, 1.003, -2.80), (.242, .013, .306),
        "Walnut_2", .004, role="computer_top_panel")
    box("Computer bottom panel", (.60, .798, -2.80), (.234, .012, .302),
        "BlackSteel", .003, role="computer_bottom_panel")
    for side, x in (("left", .481), ("right", .719)):
        box("Computer " + side + " side panel", (x, .903, -2.80),
            (.012, .194, .298), "BlackSteel", .003, role="computer_side_panel")
        for index in range(13):
            z = -2.912 + index * .018
            box("Computer " + side + " vent " + str(index + 1),
                (x + (-.0065 if side == "left" else .0065), .914, z),
                (.002, .056, .005), "Ink", .001, role="computer_vent")
    box("Computer brushed front fascia", (.60, .903, -2.644),
        (.234, .195, .013), "BrassAged", .004, role="computer_front_panel")
    box("Computer rear service panel", (.60, .903, -2.956),
        (.232, .194, .011), "BlackSteel", .003, role="computer_rear_panel")
    for index in range(12):
        box("Computer front lower vent " + str(index + 1),
            (.503 + index * .0175, .841, -2.636), (.008, .030, .003),
            "Ink", .001, role="computer_vent")
    cyl("Computer power button", (.681, .961, -2.635), .010, .005,
        "BlackSteel", 24, (math.pi / 2, 0, 0), role="computer_power_button")
    cyl("Computer power indicator", (.661, .961, -2.634), .0025, .003,
        "LampGlow", 12, (math.pi / 2, 0, 0), role="computer_status_light")
    for index, x in enumerate((.526, .562)):
        box("Computer front USB A bezel " + str(index + 1), (x, .900, -2.634),
            (.026, .012, .003), "BlackSteel", .001, role="computer_port_bezel")
        box("Computer front USB A tongue " + str(index + 1), (x, .900, -2.632),
            (.019, .003, .002), "Bone", .0004, role="computer_port_contact")
    box("Computer front USB C socket", (.611, .900, -2.634),
        (.016, .007, .003), "Ink", .002, role="computer_port")
    cyl("Computer audio jack", (.656, .900, -2.634), .004, .003,
        "Ink", 16, (math.pi / 2, 0, 0), role="computer_port")
    for name, x, width in (("Ethernet", .525, .022), ("DisplayPort", .565, .024),
                           ("HDMI", .605, .023), ("Power", .671, .018)):
        box("Computer rear " + name + " recess", (x, .858, -2.963),
            (width, .017, .004), "Ink", .002, role="computer_rear_port")
    for x in (.501, .699):
        for y in (.819, .987):
            cyl("Computer captive panel screw", (x, y, -2.964), .0035, .003,
                "BrassAged", 12, (math.pi / 2, 0, 0), role="fastener")
    for x in (.512, .688):
        for z in (-2.918, -2.682):
            cyl("Computer rubber isolation foot", (x, .7875, z), .017, .010,
                "Ink", 16, role="computer_foot")
    label = text("Computer maker badge", "HERMES", (.570, .962, -2.635), .011,
                 "Ink", role="computer_label")
    label.data.extrude = .00015
    label.data.bevel_depth = 0
    a.anchor("computer", (.60, .90, -2.80), semantic_role="workstation_computer")
    a.anchor("computer_front", (.60, .903, -2.635), normal=[0, 0, 1],
             semantic_role="computer_front_panel")
