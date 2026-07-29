; Inno Setup script — wraps dist\StatementLens.exe into StatementLens-Setup.exe.
; Build (Windows, after PyInstaller):  iscc installer\statement-lens.iss
; Produces installer\Output\StatementLens-Setup.exe.

#define AppName "Statement Lens"
#define AppVersion "1.1.0"
#define AppExe "StatementLens.exe"

[Setup]
AppId={{7E5C4B2A-1F3D-4C9E-8A2B-STATEMENTLENS}}
AppName={#AppName}
AppVersion={#AppVersion}
DefaultDirName={autopf}\StatementLens
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Per-user install by default -> no admin prompt for a non-technical user.
PrivilegesRequiredOverridesAllowed=dialog
PrivilegesRequired=lowest
OutputDir=Output
OutputBaseFilename=StatementLens-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "..\dist\StatementLens.exe"; DestDir: "{app}"; Flags: ignoreversion
; WebView2 evergreen bootstrapper — downloaded into installer\ by CI before iscc.
; Runs only when the runtime is missing (see [Run]/Check below).
Source: "MicrosoftEdgeWebview2Setup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall; Check: WebView2Missing

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
; Install the WebView2 runtime if absent, before the optional launch.
Filename: "{tmp}\MicrosoftEdgeWebview2Setup.exe"; Parameters: "/silent /install"; \
  StatusMsg: "Installing WebView2 runtime..."; Check: WebView2Missing; Flags: waituntilterminated
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[Code]
{ Detect the Evergreen WebView2 runtime via its registry marker (per-machine or
  per-user). Returns True when it is NOT installed, so the bootstrapper runs. }
function WebView2Missing: Boolean;
var
  Ver: String;
  Key: String;
begin
  Key := 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  Result := True;
  if RegQueryStringValue(HKLM, Key, 'pv', Ver) and (Ver <> '') and (Ver <> '0.0.0.0') then
    Result := False
  else if RegQueryStringValue(HKCU, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Ver) and (Ver <> '') then
    Result := False;
end;
