# LocalExtraction/gui/appname.py
"""The program's own name in the Dock, the app switcher (⌘-Tab) and the menu bar of macOS, in place of “python”:
the program runs inside the Python interpreter, which macOS would otherwise name it after.

Two macOS calls, through ctypes (no extra package):
  - the name LaunchServices shows for this running app (_LSSetApplicationInformationItem, the call Chromium makes for
    its helper processes): the Dock and the app switcher;
  - CFBundleName / CFBundleDisplayName of the main bundle's information: what the menu bar may read.

Elsewhere (Windows, Linux) nothing is done: their taskbars take the window's title and icon. Any failure is silent —
a name is never worth stopping the program for."""

from __future__ import annotations

import ctypes
import ctypes.util
import logging
import sys

NAME = "MoukhlijMatExtract"
_LAUNCH_SERVICES = ("/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/"
                    "LaunchServices")
_UTF8 = 0x08000100
_done = []


def _cf_string(cf, text: str):
    return cf.CFStringCreateWithCString(None, text.encode("utf-8"), _UTF8)


def _bundle_name(name: str) -> None:
    objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
    ctypes.cdll.LoadLibrary(ctypes.util.find_library("Foundation"))
    objc.objc_getClass.restype, objc.objc_getClass.argtypes = ctypes.c_void_p, [ctypes.c_char_p]
    objc.sel_registerName.restype, objc.sel_registerName.argtypes = ctypes.c_void_p, [ctypes.c_char_p]
    address = ctypes.cast(objc.objc_msgSend, ctypes.c_void_p).value
    # objc_msgSend called through exact prototypes (required on Apple silicon).
    send = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(address)
    send_text = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p)(address)
    answers = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(address)
    send_pair = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(address)
    sel, cls = objc.sel_registerName, objc.objc_getClass
    string = lambda text: send_text(cls(b"NSString"), sel(b"stringWithUTF8String:"), text.encode("utf-8"))  # noqa: E731
    bundle = send(cls(b"NSBundle"), sel(b"mainBundle"))
    for getter in (b"localizedInfoDictionary", b"infoDictionary"):
        info = send(bundle, sel(getter))
        # Only a dictionary that can be changed: an unchangeable one would raise inside Objective-C.
        if info and answers(info, sel(b"respondsToSelector:"), sel(b"setObject:forKey:")):
            for key in ("CFBundleName", "CFBundleDisplayName"):
                send_pair(info, sel(b"setObject:forKey:"), string(name), string(key))


def _launch_services_name(name: str) -> bool:
    ls = ctypes.cdll.LoadLibrary(_LAUNCH_SERVICES)
    cf = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreFoundation"))
    cf.CFStringCreateWithCString.restype = ctypes.c_void_p
    cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
    ls._LSGetCurrentApplicationASN.restype = ctypes.c_void_p
    ls._LSSetApplicationInformationItem.restype = ctypes.c_int
    ls._LSSetApplicationInformationItem.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                                    ctypes.c_void_p]
    asn = ls._LSGetCurrentApplicationASN()
    if not asn:
        return False
    key = ctypes.c_void_p.in_dll(ls, "_kLSDisplayNameKey").value
    return ls._LSSetApplicationInformationItem(-2, asn, key, _cf_string(cf, name), None) == 0  # -2: this session


def set_app_name(name: str = NAME, platform: str = sys.platform) -> bool:
    """Names the running program `name` in the Dock, the app switcher and the menu bar (macOS), once a window of Tk
    exists (it is what makes the program an app). Returns whether it did."""
    if platform != "darwin":
        return False
    if _done:
        return True
    try:
        _bundle_name(name)
        named = _launch_services_name(name)
    except Exception:  # an older or newer macOS without these calls: the program keeps the name it had
        logging.getLogger(__name__).debug("The app could not be named", exc_info=True)
        return False
    if named:
        _done.append(name)
    return named
