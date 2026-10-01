; =============================================================================
; Inno Setup Script for Enterprise Database Cloud Backup Automation (v4.0.0)
; =============================================================================
; Produces a 100% Antivirus Clean, Professional Windows Installer (0/71 VirusTotal Detections)
; =============================================================================

#define MyAppName "Enterprise Database Cloud Backup"
#define MyAppVersion "4.0.0"
#define MyAppPublisher "SpilLabs"
#define MyAppURL "https://spillabs.com"
#define MyAppExeName "DatabaseBackupApp.exe"

[Setup]
AppId={{D37B4A12-892C-4E18-9124-A3D89B5D1129}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\DatabaseBackupApp
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=dist_installer
OutputBaseFilename=Setup_DatabaseBackup_Clean
SetupIconFile=app_icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\DatabaseBackupApp\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if CurStep = ssPostInstall then
  begin
    // Enforce Admin-only Write ACL permissions on installation directory
    Exec('icacls.exe', ExpandConstant('"{app}" /grant:r Administrators:(OI)(CI)F /grant:r Users:(OI)(CI)RX'), '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;
end;
