Option Explicit

Dim shell
Dim fso
Dim projectDir
Dim command

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' Portable: use the folder where this .vbs file is located.
projectDir = fso.GetParentFolderName(WScript.ScriptFullName)

shell.CurrentDirectory = projectDir
shell.Environment("PROCESS")("PYTHONDONTWRITEBYTECODE") = "1"

' Uses pythonw.exe so no terminal window opens.
' The Tkinter bot GUI should still open normally.
command = "pythonw.exe -B ""run_bot.py"""

shell.Run command, 1, False
