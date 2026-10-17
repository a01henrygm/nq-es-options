' Runs run_background.bat with no window. Called by the scheduled task created by install_autostart.bat.
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
CreateObject("WScript.Shell").Run "cmd /c """ & here & "\run_background.bat""", 0, False
