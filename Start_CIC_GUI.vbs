Option Explicit

Dim shell, fso, root
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

root = fso.GetParentFolderName(WScript.ScriptFullName)
If LCase(fso.GetFileName(root)) = "launchers" Then
    root = fso.GetParentFolderName(root)
End If

shell.CurrentDirectory = root
shell.Environment("PROCESS")("PYTHONDONTWRITEBYTECODE") = "1"

Dim command
command = "cmd.exe /c python -B ""run_gui.py"""
shell.Run command, 0, False
