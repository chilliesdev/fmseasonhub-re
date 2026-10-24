"""Exercise the native menu and Cocoa key-equivalent dispatch."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from window_macos import install_window_menu

if sys.platform == 'darwin':
    import AppKit

    class MinimizeResponder(AppKit.NSResponder):
        def performMiniaturize_(self, sender):
            self.calls += 1


@unittest.skipUnless(sys.platform == 'darwin', 'Requires Cocoa')
class MacWindowMenuTests(unittest.TestCase):
    def setUp(self):
        self.app = AppKit.NSApplication.sharedApplication()
        self.old_main = self.app.mainMenu()
        self.old_windows = self.app.windowsMenu()
        self.old_responder = self.app.nextResponder()
        self.app.setWindowsMenu_(AppKit.NSMenu.alloc().initWithTitle_('Window'))
        self.menu = AppKit.NSMenu.alloc().initWithTitle_('Main')
        self.menu.addItemWithTitle_action_keyEquivalent_('Existing', None, '')
        self.app.setMainMenu_(self.menu)

    def tearDown(self):
        self.app.setNextResponder_(self.old_responder)
        self.app.setWindowsMenu_(self.old_windows)
        self.app.setMainMenu_(self.old_main)

    def test_command_m_dispatches_to_native_responder(self):
        responder = MinimizeResponder.alloc().init()
        responder.calls = 0
        self.app.setNextResponder_(responder)
        install_window_menu()
        event = AppKit.NSEvent.keyEventWithType_location_modifierFlags_timestamp_windowNumber_context_characters_charactersIgnoringModifiers_isARepeat_keyCode_(
            AppKit.NSEventTypeKeyDown, (0, 0), AppKit.NSEventModifierFlagCommand,
            0, 0, None, 'm', 'm', False, 46,
        )
        self.assertTrue(self.menu.performKeyEquivalent_(event))
        self.assertEqual(responder.calls, 1)

    def test_repeated_setup_preserves_menus_without_duplicate_commands(self):
        install_window_menu()
        menu = self.app.windowsMenu()
        menu.addItemWithTitle_action_keyEquivalent_('Existing window command', None, '')
        install_window_menu()
        self.assertEqual(self.menu.itemAtIndex_(0).title(), 'Existing')
        self.assertEqual(self.menu.numberOfItems(), 2)
        self.assertEqual(self.app.windowsMenu(), menu)
        self.assertEqual([str(item.title()) for item in menu.itemArray()],
                         ['Minimize', 'Existing window command'])


if __name__ == '__main__':
    unittest.main()
