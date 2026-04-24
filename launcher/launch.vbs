' ==============================================================
' launch.vbs
'   바탕화면 아이콘(또는 시작프로그램)에서 호출되는 진입점.
'   1) launcher/.env 를 파싱해서 APP_URL, BACKEND_URL, BACKEND_PORT 로드
'   2) 백엔드 /health 를 먼저 확인 (이미 켜져 있으면 건너뜀)
'   3) 안 켜져 있으면 start_server.bat 을 창 없이 백그라운드 실행
'   4) /health 가 200 을 줄 때까지 최대 15초 폴링
'   5) 기본 브라우저로 APP_URL 열기
' ==============================================================

Option Explicit

Dim fso, shell
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

' --- 1. 경로 구성 -------------------------------------------------
Dim scriptPath, scriptDir, envPath, batPath
scriptPath = WScript.ScriptFullName
scriptDir  = fso.GetParentFolderName(scriptPath)      ' .../launcher
envPath    = scriptDir & "\.env"
batPath    = scriptDir & "\start_server.bat"

' --- 2. .env 파싱 -------------------------------------------------
Dim appUrl, backendUrl, backendPort
appUrl      = "http://localhost:3000"
backendUrl  = "http://127.0.0.1:8000"
backendPort = "8000"

If fso.FileExists(envPath) Then
    Dim f, line, eq, key, val
    Set f = fso.OpenTextFile(envPath, 1)
    Do While Not f.AtEndOfStream
        line = Trim(f.ReadLine)
        If Len(line) > 0 And Left(line, 1) <> "#" Then
            eq = InStr(line, "=")
            If eq > 0 Then
                key = Trim(Left(line, eq - 1))
                val = Trim(Mid(line, eq + 1))
                Select Case key
                    Case "APP_URL"      : appUrl      = val
                    Case "BACKEND_URL"  : backendUrl  = val
                    Case "BACKEND_PORT" : backendPort = val
                End Select
            End If
        End If
    Loop
    f.Close
End If

' --- 3. 서버 기동 여부 확인 + 필요 시 실행 ------------------------
If Not IsServerUp(backendUrl) Then
    ' 창 없이 백그라운드 실행. 0 = hidden, False = non-blocking.
    shell.Run """" & batPath & """ " & backendPort, 0, False

    ' --- 4. 헬스체크 폴링 (최대 15초) -----------------------------
    Dim i
    For i = 1 To 30
        WScript.Sleep 500
        If IsServerUp(backendUrl) Then Exit For
    Next
End If

' --- 5. 기본 브라우저로 앱 URL 열기 -------------------------------
shell.Run """" & appUrl & """", 1, False

' ----------------------------------------------------------------
' 함수: IsServerUp
'   backendUrl + "/health" 로 GET 요청. 200이면 True.
' ----------------------------------------------------------------
Function IsServerUp(baseUrl)
    Dim http, ok
    ok = False
    On Error Resume Next
    Set http = CreateObject("MSXML2.XMLHTTP")
    http.Open "GET", baseUrl & "/health", False
    http.setRequestHeader "Cache-Control", "no-cache"
    http.Send
    If Err.Number = 0 Then
        If http.Status = 200 Then ok = True
    End If
    On Error Goto 0
    IsServerUp = ok
End Function
