' YouTube Playlist Automator — 콘솔 창 없이 백엔드 실행
' install_autostart.bat에서 시작프로그램으로 등록됨

Set WshShell = CreateObject("WScript.Shell")
strDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)

' 이미 실행 중인지 체크 (port 8000)
Set objExec = WshShell.Exec("powershell -Command ""if(Get-NetTCPConnection -LocalPort 8000 -EA SilentlyContinue){exit 1}else{exit 0}""")
Do While objExec.Status = 0
    WScript.Sleep 100
Loop
If objExec.ExitCode = 1 Then
    WScript.Quit 0
End If

' 백엔드 실행 (창 없이)
WshShell.Run "cmd /c ""cd /d " & strDir & "\backend && d:\coding\.venv\Scripts\uvicorn main:app --reload --port 8000 --host 0.0.0.0""", 0, False
