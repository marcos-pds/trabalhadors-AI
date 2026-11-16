!include "nsDialogs.nsh"
!include "LogicLib.nsh"

Var CentralVoiceSelected
Var CentralOllamaSelected
Var CentralQwenSelected
Var CentralLlamaSelected
Var CentralDockerSelected
Var CentralVoiceControl
Var CentralOllamaControl
Var CentralQwenControl
Var CentralLlamaControl
Var CentralDockerControl

Function centralOptionsCreate
  ${If} ${Silent}
    Abort
  ${EndIf}
  nsDialogs::Create 1018
  Pop $0
  ${If} $0 == error
    Abort
  ${EndIf}
  ${NSD_CreateLabel} 0 0 100% 23u "Componentes opcionais"
  Pop $0
  ${NSD_CreateLabel} 0 25u 100% 23u "Escolha o que deseja instalar. Nada sera baixado sem sua selecao."
  Pop $0
  ${NSD_CreateCheckbox} 0 56u 100% 15u "VoiceStudio + modelo OmniVoice (voz local)"
  Pop $CentralVoiceControl
  ${NSD_CreateCheckbox} 0 80u 100% 15u "Ollama (motor de modelos locais)"
  Pop $CentralOllamaControl
  ${NSD_CreateCheckbox} 12u 103u 100% 15u "Qwen 2.5 Coder 3B (programacao)"
  Pop $CentralQwenControl
  ${NSD_CreateCheckbox} 12u 126u 100% 15u "Llama 3.2 3B (conversas)"
  Pop $CentralLlamaControl
  ${NSD_CreateCheckbox} 0 151u 100% 15u "Docker Desktop (tarefas isoladas)"
  Pop $CentralDockerControl
  ${NSD_CreateLabel} 0 179u 100% 32u "Modelos podem ocupar varios GB. Alguns componentes exigem aceite de licenca ou configuracao do Windows."
  Pop $0
  nsDialogs::Show
FunctionEnd

Function centralOptionsLeave
  ${NSD_GetState} $CentralVoiceControl $CentralVoiceSelected
  ${NSD_GetState} $CentralOllamaControl $CentralOllamaSelected
  ${NSD_GetState} $CentralQwenControl $CentralQwenSelected
  ${NSD_GetState} $CentralLlamaControl $CentralLlamaSelected
  ${NSD_GetState} $CentralDockerControl $CentralDockerSelected
FunctionEnd

!macro customWelcomePage
  !insertmacro MUI_PAGE_WELCOME
  Page custom centralOptionsCreate centralOptionsLeave
!macroend

!macro customInstall
  ${IfNot} ${isUpdated}
    StrCpy $0 ""
    ${If} $CentralVoiceSelected == ${BST_CHECKED}
      StrCpy $0 "$0 -Voice"
    ${EndIf}
    ${If} $CentralOllamaSelected == ${BST_CHECKED}
      StrCpy $0 "$0 -Ollama"
    ${EndIf}
    ${If} $CentralQwenSelected == ${BST_CHECKED}
      StrCpy $0 "$0 -Qwen"
    ${EndIf}
    ${If} $CentralLlamaSelected == ${BST_CHECKED}
      StrCpy $0 "$0 -Llama"
    ${EndIf}
    ${If} $CentralDockerSelected == ${BST_CHECKED}
      StrCpy $0 "$0 -Docker"
    ${EndIf}
    ${If} $0 != ""
      DetailPrint "Instalando componentes selecionados..."
      File /oname=$PLUGINSDIR\central-optional.ps1 "${BUILD_RESOURCES_DIR}\optional-components.ps1"
      ExecWait '"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -STA -File "$PLUGINSDIR\central-optional.ps1" $0' $1
      ${If} $1 != 0
        MessageBox MB_ICONEXCLAMATION|MB_OK "A Central foi instalada. Alguns componentes opcionais nao foram concluidos. Consulte o registro em AppData\Local\Central."
      ${EndIf}
    ${EndIf}
  ${EndIf}
!macroend
