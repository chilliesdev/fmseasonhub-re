"""Native window commands missing from pywebview's default macOS menus."""


def install_window_menu():
    """Install the standard responder-chain action on the Cocoa main thread."""
    from AppKit import NSApplication, NSEventModifierFlagCommand, NSMenu, NSMenuItem

    app = NSApplication.sharedApplication()
    menu = app.windowsMenu()
    if menu is None:
        menu = NSMenu.alloc().initWithTitle_('Window')
    if not any(item.submenu() == menu for item in app.mainMenu().itemArray()):
        item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_('Window', None, '')
        item.setSubmenu_(menu)
        app.mainMenu().addItem_(item)
    app.setWindowsMenu_(menu)

    if not any(str(item.action()) == 'performMiniaturize:' for item in menu.itemArray()):
        item = menu.insertItemWithTitle_action_keyEquivalent_atIndex_(
            'Minimize', 'performMiniaturize:', 'm', 0,
        )
        item.setKeyEquivalentModifierMask_(NSEventModifierFlagCommand)
        # A nil target lets AppKit choose the focused window and validate the item.
        item.setTarget_(None)
