"""Capture native error dialogs of an explicitly owned Windows process."""
import ctypes
from ctypes import wintypes
import os


def error_response(dialog):
    if dialog['class'] != '#32770':
        return None
    buttons = {child['id'] for child in dialog['children'] if child['class'] == 'Button'}
    if dialog['title'] == 'NDF parsing error. Retry?' and 7 in buttons:
        return 7
    if dialog['title'] == 'Fatal error':
        if 1 in buttons:
            return 1
        if buttons == {2}:
            return 2
    return None


class ProcessDialogs:
    def __init__(self, pid):
        if os.name != 'nt':
            raise OSError('Native dialog capture requires Windows')
        if type(pid) is not int or pid <= 0:
            raise ValueError('Expected an owned process ID')
        self.pid = pid
        self.api = ctypes.WinDLL('user32', use_last_error=True)
        self.callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        signatures = {
            'EnumWindows': ([self.callback_type, wintypes.LPARAM], wintypes.BOOL),
            'EnumChildWindows': ([wintypes.HWND, self.callback_type, wintypes.LPARAM], wintypes.BOOL),
            'GetWindowThreadProcessId': ([wintypes.HWND, ctypes.POINTER(wintypes.DWORD)], wintypes.DWORD),
            'IsWindowVisible': ([wintypes.HWND], wintypes.BOOL),
            'GetWindowTextW': ([wintypes.HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
            'GetClassNameW': ([wintypes.HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
            'GetDlgCtrlID': ([wintypes.HWND], ctypes.c_int),
            'GetDlgItem': ([wintypes.HWND, ctypes.c_int], wintypes.HWND),
            'PostMessageW': ([wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM], wintypes.BOOL),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self.api, name)
            function.argtypes = arguments
            function.restype = result

    def owns(self, handle):
        owner = wintypes.DWORD()
        self.api.GetWindowThreadProcessId(handle, ctypes.byref(owner))
        return owner.value == self.pid

    def describe(self, handle):
        title = ctypes.create_unicode_buffer(65536)
        name = ctypes.create_unicode_buffer(256)
        self.api.GetWindowTextW(handle, title, len(title))
        self.api.GetClassNameW(handle, name, len(name))
        return {'handle': int(handle), 'title': title.value, 'class': name.value,
                'id': self.api.GetDlgCtrlID(handle)}

    def collect(self, desktop=False):
        dialogs = []

        def visit(handle, unused):
            if (not desktop and not self.owns(handle)) or not self.api.IsWindowVisible(handle):
                return True
            dialog = self.describe(handle)
            owner = wintypes.DWORD()
            self.api.GetWindowThreadProcessId(handle, ctypes.byref(owner))
            dialog['pid'] = owner.value
            if dialog['class'] != '#32770':
                return True
            children = []

            def child_visit(child, unused_child):
                children.append(self.describe(child))
                return True

            self.api.EnumChildWindows(handle, self.callback_type(child_visit), 0)
            dialog['children'] = children
            dialogs.append(dialog)
            return True

        if not self.api.EnumWindows(self.callback_type(visit), 0):
            raise ctypes.WinError(ctypes.get_last_error())
        return dialogs

    def dismiss_error(self, dialog):
        response = error_response(dialog)
        if response is None or not self.owns(dialog['handle']):
            return False
        button = self.api.GetDlgItem(dialog['handle'], response)
        if not button or not self.owns(button):
            return False
        return bool(self.api.PostMessageW(button, 0x00F5, 0, 0))
