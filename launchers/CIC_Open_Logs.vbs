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

Dim logsPath
logsPath = fso.BuildPath(root, "logs")

If Not fso.FolderExists(logsPath) Then
    fso.CreateFolder(logsPath)
End If

shell.Run "explorer.exe """ & logsPath & """", 1, False
