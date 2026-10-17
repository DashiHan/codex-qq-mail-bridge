"""Windows Credential Manager. No plaintext fallback and no secret logging."""
import ctypes
from ctypes import wintypes as w
import os


class CREDENTIAL(ctypes.Structure):
    _fields_ = [('Flags', w.DWORD), ('Type', w.DWORD), ('TargetName', w.LPWSTR),
                ('Comment', w.LPWSTR), ('LastWritten', w.FILETIME),
                ('CredentialBlobSize', w.DWORD), ('CredentialBlob', ctypes.POINTER(w.BYTE)),
                ('Persist', w.DWORD), ('AttributeCount', w.DWORD), ('Attributes', ctypes.c_void_p),
                ('TargetAlias', w.LPWSTR), ('UserName', w.LPWSTR)]


def api():
    if os.name != 'nt':
        raise ValueError('此凭据存储仅支持 Windows。')
    dll = ctypes.WinDLL('Advapi32.dll', use_last_error=True)
    dll.CredWriteW.argtypes = [ctypes.POINTER(CREDENTIAL), w.DWORD]
    dll.CredWriteW.restype = w.BOOL
    dll.CredReadW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.POINTER(ctypes.POINTER(CREDENTIAL))]
    dll.CredReadW.restype = w.BOOL
    dll.CredFree.argtypes = [ctypes.c_void_p]
    dll.CredFree.restype = None
    dll.CredDeleteW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD]
    dll.CredDeleteW.restype = w.BOOL
    return dll


def target(account):
    return 'QQJobMailer/SMTP/' + account.lower()


def put(account, secret):
    blob = ctypes.create_string_buffer(secret.encode('utf-16-le'))
    cred = CREDENTIAL()
    cred.Type, cred.TargetName, cred.UserName = 1, target(account), account
    cred.Persist = 2  # local machine, current Windows user
    cred.CredentialBlobSize = len(secret.encode('utf-16-le'))
    cred.CredentialBlob = ctypes.cast(blob, ctypes.POINTER(w.BYTE))
    try:
        if not api().CredWriteW(ctypes.byref(cred), 0):
            raise ValueError('Windows 凭据保存失败，错误码 ' + str(ctypes.get_last_error()))
    finally:
        ctypes.memset(blob, 0, ctypes.sizeof(blob))


def get(account):
    dll = api()
    ptr = ctypes.POINTER(CREDENTIAL)()
    if not dll.CredReadW(target(account), 1, 0, ctypes.byref(ptr)):
        raise ValueError('无法读取 Windows 凭据，请在本地运行 setup。')
    try:
        return ctypes.string_at(ptr.contents.CredentialBlob, ptr.contents.CredentialBlobSize).decode('utf-16-le')
    finally:
        if ptr.contents.CredentialBlobSize:
            ctypes.memset(ptr.contents.CredentialBlob, 0, ptr.contents.CredentialBlobSize)
        dll.CredFree(ptr)


def delete(account):
    if not api().CredDeleteW(target(account), 1, 0) and ctypes.get_last_error() != 1168:
        raise ValueError('凭据删除失败。')
