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

Dim logsPath, outPath, command
logsPath = fso.BuildPath(root, "logs")
If Not fso.FolderExists(logsPath) Then
    fso.CreateFolder(logsPath)
End If

outPath = fso.BuildPath(logsPath, "launcher_log_report.txt")

command = "cmd.exe /c python -B -m crafting_bot.cli.log_report  > """ & outPath & """ 2>&1"
shell.Run command, 0, True

shell.Run "notepad.exe """ & outPath & """", 1, False
