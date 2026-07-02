' LeIA — inicia o aplicativo SEM mostrar nenhuma janela de console/python.
' O launcher.bat roda oculto; quem aparece é só a janela do próprio app
' (e, na primeira execução, a janela de configuração).
Dim shell, appDir
appDir = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
Set shell = CreateObject("WScript.Shell")
shell.CurrentDirectory = appDir
shell.Run """" & appDir & "launcher.bat""", 0, False
