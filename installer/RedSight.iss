; ===========================================================================
;  RedSight Desktop - Windows installer
;
;  Built with Inno Setup 6. Compile with installer\build\Build-Installer.ps1,
;  which stages the application payload, the bundled Python runtime and the
;  offline wheelhouse into a staging tree and then invokes ISCC on this script.
;
;  Required preprocessor defines (all supplied by Build-Installer.ps1):
;    AppVersion   product version, e.g. 11.3.0
;    PayloadDir   staged application tree that becomes {app}
;    OutputDir    where the compiled setup exe is written
;    OutputBase   base name of the setup exe
;
;  Optional:
;    IconFile     path to the setup/app icon
; ===========================================================================

#ifndef AppVersion
  #define AppVersion "11.3.0"
#endif
#ifndef PayloadDir
  #error PayloadDir must be defined (pass /DPayloadDir=... to ISCC)
#endif
#ifndef OutputDir
  #define OutputDir "."
#endif
#ifndef OutputBase
  #define OutputBase "RedSight-Setup-" + AppVersion
#endif

#define AppName        "RedSight"
#define AppPublisher   "RedSight"
#define AppURL         "https://redsight.ai"
#define AppExeName     "RedSight.lnk"
; Keeping the original AppId means this build upgrades an existing 11.2.0
; install in place instead of appearing as a second product.
#define AppId          "{{B6C1E9C2-6E2E-4C7B-9B2C-REDSIGHT01}"

[Setup]
AppId={#AppId}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}
VersionInfoDescription={#AppName} Desktop Setup

DefaultDirName={autopf}\RedSight
DefaultGroupName=RedSight
DisableProgramGroupPage=yes
AllowNoIcons=yes
UninstallDisplayName={#AppName} {#AppVersion}
#ifdef IconFile
UninstallDisplayIcon={app}\assets\redsight.ico
SetupIconFile={#IconFile}
#endif

; RedSight needs 64-bit Windows 10/11: the Docker WSL2 backend and the
; PySide6/torch wheels are x64-only.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19041

; Setup provisions Docker Desktop, enables Windows features and writes to
; Program Files, all of which require elevation. There is no non-admin mode.
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=

OutputDir={#OutputDir}
OutputBaseFilename={#OutputBase}
Compression=lzma2/max
SolidCompression=yes
LZMANumBlockThreads=4
WizardStyle=modern
ShowLanguageDialog=no
SetupLogging=yes
CloseApplications=yes
RestartApplications=no
ChangesEnvironment=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Types]
Name: "full";   Description: "Full installation (recommended)"
Name: "custom"; Description: "Custom installation"; Flags: iscustom

[Components]
Name: "core";     Description: "RedSight application and private Python 3.12 runtime"; \
                  Types: full custom; Flags: fixed
Name: "docker";   Description: "Docker Desktop + WSL2 backend (required to run the RedSight services)"; \
                  Types: full
Name: "images";   Description: "Build the RedSight container images during setup"; \
                  Types: full
Name: "node";     Description: "Node.js LTS (only for the WhatsApp remote utility)"; \
                  Types: custom

[Tasks]
Name: "desktopicon";  Description: "Create a &Desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "preferSystemPython"; Description: "Use an existing Python 3.12 from PATH instead of the bundled runtime"; \
                  GroupDescription: "Advanced:"; Flags: unchecked
Name: "offline";  Description: "Offline install - never download (requires a prepared bundle)"; \
                  GroupDescription: "Advanced:"; Flags: unchecked

[Dirs]
; Virtual environments and runtime state are created by setup, not shipped.
Name: "{app}\.venv-ui";        Flags: uninsalwaysuninstall
Name: "{app}\.venv-actions";   Flags: uninsalwaysuninstall
Name: "{app}\runtime";         Flags: uninsalwaysuninstall
Name: "{app}\logs";            Flags: uninsalwaysuninstall

[Files]
; ---------------------------------------------------------------------------
; The staged application tree. Build-Installer.ps1 has already removed
; virtualenvs, caches, node_modules and private data, and has overlaid the
; updated setup scripts into scripts\windows.
; ---------------------------------------------------------------------------
Source: "{#PayloadDir}\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs; Components: core

[Icons]
Name: "{group}\RedSight"; \
    Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; \
    Parameters: "-NoLogo -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""{app}\LAUNCH-REDSIGHT-DESKTOP.ps1"""; \
    IconFilename: "{app}\assets\redsight.ico"; WorkingDir: "{app}"; \
    Comment: "RedSight Command Center"; Check: HasDesktopLauncher
Name: "{group}\RedSight"; \
    Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; \
    Parameters: "-NoLogo -NoProfile -ExecutionPolicy Bypass -File ""{app}\START-REDSIGHT.ps1"""; \
    IconFilename: "{app}\assets\redsight.ico"; WorkingDir: "{app}"; \
    Comment: "RedSight Command Center"; Check: NotHasDesktopLauncher
Name: "{group}\RedSight health check"; \
    Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; \
    Parameters: "-NoLogo -NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\windows\Verify-RedSightSetup.ps1"""; \
    WorkingDir: "{app}"; Comment: "Check that RedSight can launch"
Name: "{group}\Repair RedSight setup"; \
    Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; \
    Parameters: "-NoLogo -NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\windows\Bootstrap-RedSight.ps1"" -InstallDocker -EnableWsl"; \
    WorkingDir: "{app}"; Comment: "Re-run RedSight dependency setup"
Name: "{group}\Uninstall RedSight"; Filename: "{uninstallexe}"

[Run]
; ---------------------------------------------------------------------------
; First-run setup. This is the whole point of the installer: on exit, every
; dependency RedSight needs is present and configured.
;
; runascurrentuser is deliberate - setup already runs elevated, and the
; virtualenvs, Docker group membership and Desktop shortcut must belong to the
; installing user rather than to a separate admin account.
; ---------------------------------------------------------------------------
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; \
    Parameters: "-NoLogo -NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\windows\Bootstrap-RedSight.ps1"" -ProjectRoot ""{app}"" {code:GetBootstrapArgs}"; \
    WorkingDir: "{app}"; \
    StatusMsg: "Installing dependencies (Python, virtual environments, Docker) - this can take a while..."; \
    Flags: runascurrentuser waituntilterminated; \
    Components: core

; Offer the health check and a first launch at the end of setup.
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; \
    Parameters: "-NoLogo -NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\windows\Verify-RedSightSetup.ps1"""; \
    WorkingDir: "{app}"; Description: "Run the RedSight health check"; \
    Flags: postinstall runascurrentuser skipifsilent
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; \
    Parameters: "-NoLogo -NoProfile -ExecutionPolicy Bypass -File ""{app}\START-REDSIGHT.ps1"""; \
    WorkingDir: "{app}"; Description: "Launch RedSight now"; \
    Flags: postinstall nowait runascurrentuser skipifsilent unchecked

[UninstallRun]
; Ask about containers/images and data volumes separately, so a reinstall can
; keep the Qdrant index and chat memory.
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; \
    Parameters: "-NoLogo -NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\windows\Uninstall-RedSightDocker.ps1"""; \
    WorkingDir: "{app}"; RunOnceId: "RedSightDockerCleanup"; Flags: runhidden; \
    Check: ShouldCleanDocker

[UninstallDelete]
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\.venv-ui"
Type: filesandordirs; Name: "{app}\.venv-actions"
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\logs"
Type: filesandordirs; Name: "{app}\__pycache__"

[Messages]
WelcomeLabel2=This will install [name/ver] on your computer.%n%nSetup checks for everything RedSight needs - Python 3.12, its virtual environments, WSL2 and Docker Desktop - and installs and configures whatever is missing. A private Python 3.12 runtime is included, so no separate Python installation is required.%n%nAn internet connection is needed unless you are installing from a prepared offline bundle.

[Code]
var
  RebootNeeded: Boolean;

{ --------------------------------------------------------------------------
  Which launcher shipped in this payload? 11.2.0 and later carry
  LAUNCH-REDSIGHT-DESKTOP.ps1, which runs windowless and reports failures in a
  dialog; older payloads only have START-REDSIGHT.ps1.
  -------------------------------------------------------------------------- }
function HasDesktopLauncher(): Boolean;
begin
  Result := FileExists(ExpandConstant('{app}\LAUNCH-REDSIGHT-DESKTOP.ps1'));
end;

function NotHasDesktopLauncher(): Boolean;
begin
  Result := not HasDesktopLauncher();
end;

{ --------------------------------------------------------------------------
  Builds the argument list for Bootstrap-RedSight.ps1 from the components and
  tasks the user selected. Keeping this in one place means the wizard, the
  Start Menu repair shortcut and a manual re-run all behave identically.
  -------------------------------------------------------------------------- }
function GetBootstrapArgs(Param: string): string;
var
  Args: string;
begin
  Args := '';

  if WizardIsComponentSelected('docker') then
    Args := Args + ' -InstallDocker -EnableWsl'
  else
    Args := Args + ' -SkipDocker';

  if WizardIsComponentSelected('images') then
    Args := Args + ' -BuildImages';

  if WizardIsComponentSelected('node') then
    Args := Args + ' -InstallNode';

  if WizardIsTaskSelected('preferSystemPython') then
    Args := Args + ' -PreferSystemPython';

  if WizardIsTaskSelected('offline') then
    Args := Args + ' -OfflineOnly';

  { The bootstrap creates the Desktop shortcut; skip it when the task is off. }
  if not WizardIsTaskSelected('desktopicon') then
    Args := Args + ' -SkipShortcut';

  { A silent install must never wait on a console prompt. }
  if WizardSilent then
    Args := Args + ' -NonInteractive';

  Result := Trim(Args);
end;

{ --------------------------------------------------------------------------
  Pre-install environment checks. Refusing early with a clear message beats
  failing halfway through a 20-minute dependency install.
  -------------------------------------------------------------------------- }
function InitializeSetup(): Boolean;
var
  FreeMB, TotalMB: Cardinal;
begin
  Result := True;

  if not IsAdminInstallMode then
  begin
    MsgBox('RedSight setup must be run as Administrator.' + #13#10#13#10 +
           'It installs Docker Desktop, enables the WSL2 Windows features and ' +
           'writes to Program Files. Right-click the installer and choose ' +
           '"Run as administrator".', mbCriticalError, MB_OK);
    Result := False;
    Exit;
  end;

  { The app tree, the private runtime and the Python wheels (PySide6, torch,
    onnxruntime) together need several GB. Warn rather than refuse: the user
    may be installing to a different, larger volume. }
  if GetSpaceOnDisk(ExpandConstant('{sd}\'), True, FreeMB, TotalMB) then
  begin
    if FreeMB < 8192 then
    begin
      if MsgBox('Only ' + IntToStr(FreeMB) + ' MB is free on the system drive.' + #13#10#13#10 +
                'RedSight needs roughly 8 GB once its Python packages and Docker ' +
                'images are installed. Continue anyway?',
                mbConfirmation, MB_YESNO) <> IDYES then
      begin
        Result := False;
        Exit;
      end;
    end;
  end;
end;

{ --------------------------------------------------------------------------
  The bootstrap records whether enabling WSL2 requires a restart in its summary
  file. Read it back so setup can ask for the reboot rather than leaving Docker
  half-configured.
  -------------------------------------------------------------------------- }
procedure CurStepChanged(CurStep: TSetupStep);
var
  SummaryPath: string;
  Summary: AnsiString;
begin
  if CurStep = ssPostInstall then
  begin
    SummaryPath := ExpandConstant('{localappdata}\RedSight\setup-summary.json');
    if FileExists(SummaryPath) then
    begin
      Log('RedSight setup summary: ' + SummaryPath);
      if LoadStringFromFile(SummaryPath, Summary) then
      begin
        if Pos('"rebootRequired": true', Summary) > 0 then
        begin
          RebootNeeded := True;
          Log('RedSight setup reported that a restart is required.');
        end;
      end;
    end;
  end;
end;

function NeedRestart(): Boolean;
begin
  Result := RebootNeeded;
end;

function ShouldCleanDocker(): Boolean;
begin
  Result := False;
  if UninstallSilent then
    Exit;
  Result := MsgBox('Also remove the RedSight Docker containers and images?' + #13#10#13#10 +
                   'Your stored data volumes (Qdrant vector index and chat memory) are ' +
                   'handled by a separate question inside that step, so you can keep your ' +
                   'data if you plan to reinstall.',
                   mbConfirmation, MB_YESNO) = IDYES;
end;
