' Windowless desktop entry point; keep the canonical source environment/provenance checks.
Option Explicit
Dim shell, files, root, logPath, command, result
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
root = files.GetParentFolderName(WScript.ScriptFullName)
logPath = files.BuildPath(shell.ExpandEnvironmentStrings("%TEMP%"), "MorphoLabel-startup.log")
shell.CurrentDirectory = root
command = """" & shell.ExpandEnvironmentStrings("%COMSPEC%") & """ /d /s /c """"" & files.BuildPath(root, "RUN_CANONICAL.cmd") & """ shell > """ & logPath & """ 2>&1"""
result = shell.Run(command, 0, True)
If result <> 0 Then
    MsgBox "MorphoLabel could not start or stopped with an error." & vbCrLf & "Details: " & logPath, vbExclamation, "MorphoLabel"
End If
