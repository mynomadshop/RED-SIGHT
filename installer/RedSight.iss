; ===========================================================================
;  RedSight Desktop - Windows installer
;
;  Built with Inno Setup 6. Compile with installer\build\Build-Installer.ps1,
;  which stages the application payload, the bundled Python runtime and the
;  offline wheelhouse into a staging tree and then invokes ISCC on this script.
;
;  Required preprocessor defines (all supplied by Build-Installer.ps1):
;    AppVersion   product version, e.g. 11.5.1
;    PayloadDir   staged application tree that becomes {app}
;    OutputDir    where the compiled setup exe is written
;    OutputBase   base name of the setup exe
;
;  Optional:
;    IconFile     path to the setup/app icon
; ===========================================================================

#ifndef AppVersion
  #define AppVersion "11.5.1"
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
; Standalone hardware scanner, extracted to {tmp} and run by the wizard before
; anything is installed so the setup options can be tailored to this machine.
#ifndef HardwareScript
  #define HardwareScript "scripts\RedSight-Hardware.ps1"
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

; A device may hold exactly one RedSight installation. When one is already
; recorded, setup installs over it rather than beside it, and the directory page
; is skipped so a second copy cannot be created by changing the path.
DefaultDirName={code:GetInstallDir}
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
; Two copies of setup running at once would fight over the same virtualenvs and
; the same registry entry.
SetupMutex=RedSightSetup,Global\RedSightSetup

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

; Wizard-time only: never installed, just extracted to {tmp} so the hardware
; scan can run before the user chooses a setup profile.
Source: "{#HardwareScript}"; Flags: dontcopy

[Icons]
; One entry, pointing at the dispatcher. RedSight ships several launchers and
; they are not equivalent - only some start the action/memory gateway the UI
; needs for memory and for chat - so the choice is made at launch time from the
; recorded runtime mode instead of guessed here, before setup has even run.
Name: "{group}\RedSight"; \
    Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; \
    Parameters: "-NoLogo -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""{app}\scripts\windows\Start-RedSight.ps1"""; \
    IconFilename: "{app}\assets\redsight.ico"; WorkingDir: "{app}"; \
    Comment: "RedSight Command Center"
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
    Parameters: "-NoLogo -NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\windows\Start-RedSight.ps1"""; \
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
const
  PROFILE_CUDA = 0;
  PROFILE_API  = 1;

var
  ProfilePage:   TInputOptionWizardPage;
  ProviderPage:  TInputOptionWizardPage;
  ApiPage:       TInputQueryWizardPage;
  LmPage:        TInputQueryWizardPage;
  WorkspacePage: TInputDirWizardPage;
  ProfileInfo:   TNewStaticText;
  LmInfo:        TNewStaticText;
  ReduceEffects: TNewCheckBox;

  ExistingPath:  string;
  ExistingVer:   string;

  RebootNeeded:  Boolean;
  HwScanned:     Boolean;
  HwScanOk:      Boolean;
  HwIniPath:     string;
  HwJsonPath:    string;
  AnswerPath:    string;

  HwCudaCapable: Boolean;
  HwNvidiaCard:  Boolean;
  HwWsl2:        Boolean;
  HwLaptop:      Boolean;
  HwGpuName:     string;
  HwGpuNames:    string;
  HwGpuCount:    Integer;
  HwVram:        string;
  HwWslBlocker:  string;
  HwRecProfile:  string;
  HwRecRuntime:  string;

{ Provider slugs, in the order shown on ProviderPage. Must match
  app/ui/action_palette_stage105.py and RedSight-Provision.ps1. }
function ProviderSlug(Index: Integer): string;
begin
  case Index of
    0: Result := 'lmstudio';
    1: Result := 'openai';
    2: Result := 'anthropic';
    3: Result := 'gemini';
    4: Result := 'xai';
    5: Result := 'custom';
  else
    Result := 'lmstudio';
  end;
end;

function IniBool(const Section, Key: string): Boolean;
begin
  Result := GetIniString(Section, Key, '0', HwIniPath) = '1';
end;

{ ------------------------------------------------------------------------
  One installation per device.

  Inno records where a product with this AppId was installed. Reading that back
  lets setup install over the existing copy instead of beside it, and lets the
  directory page be skipped so the path cannot be changed into a second copy.
  Both registry views are checked because an earlier build may have been
  compiled without 64-bit install mode.
  ------------------------------------------------------------------------ }
procedure DetectExistingInstall();
var
  Key: string;
  Value: string;
begin
  if ExistingPath <> '' then
    Exit;

  Key := 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{#AppId}_is1';

  if RegQueryStringValue(HKLM64, Key, 'InstallLocation', Value) or
     RegQueryStringValue(HKLM32, Key, 'InstallLocation', Value) or
     RegQueryStringValue(HKCU,   Key, 'InstallLocation', Value) then
  begin
    Value := RemoveBackslashUnlessRoot(Trim(Value));
    { A recorded path whose directory is gone is a stale entry from a manual
      deletion; treating it as authoritative would install into nothing. }
    if (Value <> '') and DirExists(Value) then
    begin
      ExistingPath := Value;
      if not (RegQueryStringValue(HKLM64, Key, 'DisplayVersion', ExistingVer) or
              RegQueryStringValue(HKLM32, Key, 'DisplayVersion', ExistingVer) or
              RegQueryStringValue(HKCU,   Key, 'DisplayVersion', ExistingVer)) then
        ExistingVer := '';
      Log('existing RedSight installation found at ' + ExistingPath +
          ' (version ' + ExistingVer + ')');
    end
    else
      Log('a RedSight installation is recorded at "' + Value + '" but that directory is gone');
  end;
end;

function GetInstallDir(Param: string): string;
begin
  DetectExistingInstall();
  if ExistingPath <> '' then
    Result := ExistingPath
  else
    Result := ExpandConstant('{autopf}\RedSight');
end;

function HasExistingInstall(): Boolean;
begin
  DetectExistingInstall();
  Result := ExistingPath <> '';
end;

{ ------------------------------------------------------------------------
  Runs RedSight-Hardware.ps1 into the temp directory. Everything downstream -
  which Python wheels get downloaded, whether WSL2/Docker is attempted at all -
  depends on this, so it runs before the user is asked to choose anything.
  ------------------------------------------------------------------------ }
procedure ScanHardware();
var
  ResultCode: Integer;
  ScriptPath: string;
  Params: string;
begin
  if HwScanned then
    Exit;
  HwScanned := True;
  HwScanOk := False;

  { Conservative defaults if anything below fails. }
  HwCudaCapable := False;
  HwNvidiaCard := False;
  HwWsl2 := False;
  HwLaptop := False;
  HwGpuName := '';
  HwGpuNames := '';
  HwGpuCount := 0;
  HwVram := '0';
  HwWslBlocker := '';
  HwRecProfile := 'api';
  HwRecRuntime := 'native';

  try
    ExtractTemporaryFile('RedSight-Hardware.ps1');
  except
    Log('could not extract the hardware scanner: ' + GetExceptionMessage);
    Exit;
  end;

  ScriptPath := ExpandConstant('{tmp}\RedSight-Hardware.ps1');
  HwIniPath := ExpandConstant('{tmp}\rs-hardware.ini');
  HwJsonPath := ExpandConstant('{tmp}\rs-hardware.json');

  Params := '-NoLogo -NoProfile -ExecutionPolicy Bypass -File "' + ScriptPath + '"' +
            ' -Quiet -IniFile "' + HwIniPath + '" -OutFile "' + HwJsonPath + '"';

  WizardForm.StatusLabel.Caption := 'Checking this computer...';
  if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'), Params,
              '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    Log('hardware scan could not be started, code ' + IntToStr(ResultCode));
    Exit;
  end;

  if not FileExists(HwIniPath) then
  begin
    Log('hardware scan produced no INI at ' + HwIniPath);
    HwJsonPath := '';
    Exit;
  end;

  { The scanner writes scanOk=1 as the first key. If it does not read back, the
    INI exists but Windows cannot parse it - which is exactly what a UTF-8 BOM
    used to cause, making every value below read as its default and reporting a
    dual-GPU workstation as having neither GPU nor virtualization. Rather than
    act on defaults, discard the whole scan and let the bootstrap redo it. }
  if GetIniString('hardware', 'scanOk', '0', HwIniPath) <> '1' then
  begin
    Log('hardware INI at ' + HwIniPath + ' is present but unreadable; discarding the scan');
    HwJsonPath := '';
    Exit;
  end;
  HwScanOk := True;

  HwCudaCapable := IniBool('hardware', 'cudaCapable');
  HwNvidiaCard  := IniBool('hardware', 'hasNvidiaHardware');
  HwWsl2        := IniBool('hardware', 'wsl2Capable');
  HwLaptop      := IniBool('hardware', 'isLaptop');
  HwGpuName     := GetIniString('hardware', 'gpuName', '', HwIniPath);
  HwGpuNames    := GetIniString('hardware', 'gpuNames', '', HwIniPath);
  HwGpuCount    := StrToIntDef(GetIniString('hardware', 'nvidiaGpuCount', '0', HwIniPath), 0);
  HwVram        := GetIniString('hardware', 'maxVramGB', '0', HwIniPath);
  HwWslBlocker  := GetIniString('hardware', 'wsl2Blocker', '', HwIniPath);
  HwRecProfile  := GetIniString('hardware', 'recommendProfile', 'api', HwIniPath);
  HwRecRuntime  := GetIniString('hardware', 'recommendRuntime', 'native', HwIniPath);

  Log('hardware: cuda=' + GetIniString('hardware', 'cudaCapable', '0', HwIniPath) +
      ' nvidiaGpus=' + IntToStr(HwGpuCount) +
      ' wsl2=' + GetIniString('hardware', 'wsl2Capable', '0', HwIniPath) +
      ' recommend=' + HwRecProfile + '/' + HwRecRuntime);
end;

{ Human-readable summary shown on the setup-profile page. }
function HardwareSummary(): string;
var
  S: string;
begin
  if not HwScanOk then
  begin
    Result := 'Hardware detection did not complete on this computer, so setup cannot tell ' +
              'whether it has a CUDA GPU or can run WSL2.' + #13#10#13#10 +
              'Choose the option that matches your machine. Setup will re-check during ' +
              'installation and adjust automatically, so an incorrect choice here is not fatal.';
    Exit;
  end;

  S := 'Detected: ';
  if HwLaptop then
    S := S + 'laptop'
  else
    S := S + 'desktop';

  if HwGpuNames <> '' then
    S := S + ', ' + HwGpuNames
  else if HwGpuName <> '' then
    S := S + ', ' + HwGpuName;

  S := S + #13#10;

  if HwCudaCapable then
  begin
    if HwGpuCount > 1 then
      S := S + IntToStr(HwGpuCount) + ' NVIDIA GPUs, driver responding, ' + HwVram +
           ' GB VRAM on the largest - CUDA acceleration is available.' + #13#10
    else
      S := S + 'NVIDIA driver responding, ' + HwVram + ' GB VRAM - CUDA acceleration is available.' + #13#10;
  end
  else if HwNvidiaCard then
    S := S + 'An NVIDIA GPU is present but its driver did not respond, so CUDA packages would not load.' + #13#10
  else
    S := S + 'No CUDA-capable GPU detected.' + #13#10;

  if HwWsl2 then
    S := S + 'Virtualization is available, so the containerized backend (Docker + WSL2) can be used.'
  else
    S := S + 'WSL2/Docker unavailable: ' + HwWslBlocker + ' RedSight will run in native mode instead, which needs no containers.';

  Result := S;
end;

function IsApiProfile(): Boolean;
begin
  Result := (ProfilePage <> nil) and ProfilePage.Values[PROFILE_API];
end;

procedure InitializeWizard();
begin
  { --- Setup profile: the two initial options ------------------------------ }
  ProfilePage := CreateInputOptionPage(wpWelcome,
    'Setup type',
    'How should RedSight run on this computer?',
    'Setup checks your hardware and installs only the components this machine can actually use.',
    True, False);
  ProfilePage.Add('NVIDIA GPU - local inference with CUDA acceleration');
  ProfilePage.Add('Laptop or PC - cloud AI providers using an API key');

  ProfileInfo := TNewStaticText.Create(ProfilePage);
  ProfileInfo.Parent := ProfilePage.Surface;
  ProfileInfo.Top := ProfilePage.CheckListBox.Top + ProfilePage.CheckListBox.Height + ScaleY(12);
  ProfileInfo.Left := ProfilePage.CheckListBox.Left;
  ProfileInfo.Width := ProfilePage.SurfaceWidth;
  ProfileInfo.AutoSize := False;
  ProfileInfo.Height := ScaleY(80);
  ProfileInfo.WordWrap := True;
  ProfileInfo.Caption := '';

  { --- Provider selection (API profile only) ------------------------------- }
  ProviderPage := CreateInputOptionPage(ProfilePage.ID,
    'AI provider',
    'Which provider should RedSight use?',
    'You can change this later in RedSight Settings, under AI Provider.',
    True, False);
  ProviderPage.Add('LM Studio (local, no API key needed)');
  ProviderPage.Add('OpenAI');
  ProviderPage.Add('Anthropic Claude');
  ProviderPage.Add('Google Gemini');
  ProviderPage.Add('Grok (xAI)');
  ProviderPage.Add('Custom OpenAI-compatible endpoint');
  ProviderPage.Values[1] := True;

  { --- Provider credentials ------------------------------------------------ }
  ApiPage := CreateInputQueryPage(ProviderPage.ID,
    'Provider details',
    'Enter your API key.',
    'The key is stored encrypted for your Windows account (DPAPI), the same way the Settings dialog stores it. Leave blank to add it later in Settings.');
  ApiPage.Add('API key:', True);
  ApiPage.Add('Model (optional - leave blank for the default):', False);
  ApiPage.Add('Base URL (only for a custom OpenAI-compatible endpoint):', False);

  { --- LM Studio: the local model server ----------------------------------
    Shown whenever RedSight will use a local model - the CUDA profile always,
    and the API profile when LM Studio is the chosen provider.

    This page exists because the endpoint has to be recorded somewhere every
    RedSight process reads. The application's own default is
    http://host.docker.internal:1234/v1, which resolves only inside a
    container, and its Settings dialog tests whatever URL is typed into it
    directly - so a passing test could sit beside a backend that never reached
    LM Studio at all. }
  LmPage := CreateInputQueryPage(ApiPage.ID,
    'LM Studio',
    'Where is your local model server?',
    'Leave the default if LM Studio runs on this computer. Point it at another machine by ' +
    'entering that address. Setup tests the endpoint and records it for the backend, the ' +
    'agent gateway and the desktop UI; you can change it later in Settings -> LM Studio.');
  LmPage.Add('Endpoint:', False);
  LmPage.Add('Model (optional - leave blank to use whichever model is loaded):', False);
  LmPage.Values[0] := 'http://127.0.0.1:1234/v1';

  ReduceEffects := TNewCheckBox.Create(LmPage);
  ReduceEffects.Parent := LmPage.Surface;
  ReduceEffects.Top := LmPage.Edits[1].Top + LmPage.Edits[1].Height + ScaleY(20);
  ReduceEffects.Left := LmPage.Edits[1].Left;
  ReduceEffects.Width := LmPage.SurfaceWidth;
  ReduceEffects.Height := ScaleY(17);
  ReduceEffects.Caption := 'Reduce desktop animation (recommended)';
  ReduceEffects.Checked := True;

  LmInfo := TNewStaticText.Create(LmPage);
  LmInfo.Parent := LmPage.Surface;
  LmInfo.Top := ReduceEffects.Top + ReduceEffects.Height + ScaleY(10);
  LmInfo.Left := LmPage.Edits[1].Left;
  LmInfo.Width := LmPage.SurfaceWidth;
  LmInfo.AutoSize := False;
  LmInfo.Height := ScaleY(56);
  LmInfo.WordWrap := True;
  LmInfo.Caption := 'RedSight''s ambient visual layer repaints the whole window twenty times a ' +
                    'second from the same thread that handles the mouse, which is felt as late ' +
                    'cursor movement and late clicks on any machine. Clear this box to keep the ' +
                    'shipped look; it can also be changed later in Settings.';

  { --- Working directory --------------------------------------------------- }
  WorkspacePage := CreateInputDirPage(LmPage.ID,
    'RedSight working folder',
    'Where should RedSight keep your files?',
    'Setup creates this folder and configures RedSight to use it for projects, generated output, memory and MCP server definitions. It must be writable, so it lives under your user profile rather than in Program Files.',
    False, '');
  WorkspacePage.Add('');
  { The Documents constant is OneDrive-redirected on many machines, and its
    parent is then an arbitrary sync folder - one real install landed the
    workspace in "OneDrive\untitled folder\RedSight". The user profile
    directory is the real home, and keeping a vector database out of a sync
    root also avoids conflict copies. }
  WorkspacePage.Values[0] := ExpandConstant('{%USERPROFILE}\RedSight');
end;

function UsesLocalModel(): Boolean;
begin
  { The CUDA profile is local inference by definition; the API profile is only
    local when LM Studio is the selected provider. }
  Result := (not IsApiProfile()) or
            ((ProviderPage <> nil) and (ProviderSlug(ProviderPage.SelectedValueIndex) = 'lmstudio'));
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if (LmPage <> nil) and (CurPageID = LmPage.ID) then
  begin
    { Checked regardless of the GPU: the ambient layer's cost is a translucent
      full-window repaint driven from the Qt GUI thread, so it competes with
      input handling even on a dual high-end card - which is where the lag that
      prompted this was reported. }
    ReduceEffects.Checked := True;
  end;

  if (ProfilePage <> nil) and (CurPageID = ProfilePage.ID) then
  begin
    { Scan here rather than on the way out of the welcome page: Inno 6 disables
      the welcome page by default, so NextButtonClick(wpWelcome) never fires and
      every Hw* value would still be at its default - which silently reported
      "no GPU, no WSL2" on machines that had both. The profile page is always
      shown, and ScanHardware is guarded so this costs nothing on re-entry. }
    ScanHardware();
    ProfileInfo.Caption := HardwareSummary();
    { Preselect what the hardware actually supports, but leave the choice open. }
    if not ProfilePage.Values[PROFILE_CUDA] and not ProfilePage.Values[PROFILE_API] then
    begin
      if HwRecProfile = 'cuda' then
        ProfilePage.Values[PROFILE_CUDA] := True
      else
        ProfilePage.Values[PROFILE_API] := True;
    end;
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;

  { Scan on the way out of the welcome page so the profile page can show real
    findings without freezing the wizard at startup. }
  if CurPageID = wpWelcome then
    ScanHardware();

  if (ProfilePage <> nil) and (CurPageID = ProfilePage.ID) then
  begin
    if ProfilePage.Values[PROFILE_CUDA] and not HwCudaCapable then
    begin
      if MsgBox('No responding NVIDIA driver was detected on this computer.' + #13#10#13#10 +
                'CUDA packages are roughly 2.5 GB and will not load without one. ' +
                'Continue with the CUDA setup anyway?' + #13#10#13#10 +
                'Choose No to use the laptop / API setup instead.',
                mbConfirmation, MB_YESNO) <> IDYES then
      begin
        ProfilePage.Values[PROFILE_CUDA] := False;
        ProfilePage.Values[PROFILE_API] := True;
      end;
    end;
  end;

  { A cloud provider is useless without a key, but the user may prefer to add
    it in Settings later, so warn rather than block. }
  if (ApiPage <> nil) and (CurPageID = ApiPage.ID) then
  begin
    if (ProviderSlug(ProviderPage.SelectedValueIndex) <> 'lmstudio') and (Trim(ApiPage.Values[0]) = '') then
    begin
      if MsgBox('No API key was entered.' + #13#10#13#10 +
                'RedSight will install, but it cannot reach ' +
                ProviderSlug(ProviderPage.SelectedValueIndex) +
                ' until you add a key in Settings -> AI Provider.' + #13#10#13#10 +
                'Continue without a key?', mbConfirmation, MB_YESNO) <> IDYES then
        Result := False;
    end;
  end;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  { The provider pages only make sense for the API profile. }
  if (ProviderPage <> nil) and (PageID = ProviderPage.ID) then
    Result := not IsApiProfile();
  if (ApiPage <> nil) and (PageID = ApiPage.ID) then
    Result := (not IsApiProfile()) or (ProviderSlug(ProviderPage.SelectedValueIndex) = 'lmstudio');
  { Nothing to ask about a local server that will not be used. }
  if (LmPage <> nil) and (PageID = LmPage.ID) then
    Result := not UsesLocalModel();
  { One installation per device: the path of the existing one is not negotiable,
    because a different path would leave two copies behind. }
  if (PageID = wpSelectDir) and HasExistingInstall() then
    Result := True;
end;

{ ------------------------------------------------------------------------
  Writes the wizard's answers to an INI file in the temp directory and returns
  the bootstrap arguments.

  The API key goes in the file rather than on the command line: Inno logs the
  parameters of every [Run] entry, and a command line is visible to any process
  on the machine. The bootstrap overwrites and deletes the file once read.
  ------------------------------------------------------------------------ }
function GetBootstrapArgs(Param: string): string;
var
  Args: string;
  Lines: TArrayOfString;
  Count: Integer;
  Slug: string;
  Workspace: string;
  DockerWanted: Boolean;
begin
  { Last-resort guard: a silent install shows no pages at all, so nothing above
    would have scanned. Never decide Docker/CUDA from unscanned defaults. }
  ScanHardware();

  AnswerPath := ExpandConstant('{tmp}\rs-answers.ini');

  SetArrayLength(Lines, 24);
  Count := 0;
  Lines[Count] := '[setup]'; Count := Count + 1;

  if (ProfilePage <> nil) and ProfilePage.Values[PROFILE_CUDA] then
    Lines[Count] := 'profile=cuda'
  else if (ProfilePage <> nil) and ProfilePage.Values[PROFILE_API] then
    Lines[Count] := 'profile=api'
  else
    Lines[Count] := 'profile=auto';
  Count := Count + 1;

  { Containers require BOTH the component and a machine that can run WSL2.
    Anything else is native - stated outright rather than left as 'auto', so the
    bootstrap never has to re-derive a decision the wizard already made. }
  DockerWanted := WizardIsComponentSelected('docker') and HwWsl2;
  if HwScanOk then
  begin
    if DockerWanted then
      Lines[Count] := 'runtimeMode=container'
    else
      Lines[Count] := 'runtimeMode=native';
    Count := Count + 1;
  end;
  { When the scan failed the key is omitted entirely: the bootstrap's default is
    'auto', which makes it scan for itself rather than inherit a guess. }

  Workspace := '';
  if WorkspacePage <> nil then
    Workspace := Trim(WorkspacePage.Values[0]);
  if Workspace <> '' then
  begin
    Lines[Count] := 'workspace=' + Workspace; Count := Count + 1;
  end;

  if IsApiProfile() and (ProviderPage <> nil) then
  begin
    Slug := ProviderSlug(ProviderPage.SelectedValueIndex);
    Lines[Count] := 'provider=' + Slug; Count := Count + 1;
    if ApiPage <> nil then
    begin
      if Trim(ApiPage.Values[0]) <> '' then
      begin
        Lines[Count] := 'apiKey=' + Trim(ApiPage.Values[0]); Count := Count + 1;
      end;
      if Trim(ApiPage.Values[1]) <> '' then
      begin
        Lines[Count] := 'model=' + Trim(ApiPage.Values[1]); Count := Count + 1;
      end;
      if Trim(ApiPage.Values[2]) <> '' then
      begin
        Lines[Count] := 'baseUrl=' + Trim(ApiPage.Values[2]); Count := Count + 1;
      end;
    end;
  end;

  if UsesLocalModel() and (LmPage <> nil) then
  begin
    if Trim(LmPage.Values[0]) <> '' then
    begin
      Lines[Count] := 'lmStudioUrl=' + Trim(LmPage.Values[0]); Count := Count + 1;
    end;
    if Trim(LmPage.Values[1]) <> '' then
    begin
      Lines[Count] := 'lmStudioModel=' + Trim(LmPage.Values[1]); Count := Count + 1;
    end;
  end;

  if ReduceEffects <> nil then
  begin
    if ReduceEffects.Checked then
      Lines[Count] := 'uiEffects=reduced'
    else
      Lines[Count] := 'uiEffects=full';
    Count := Count + 1;
  end;

  if HwJsonPath <> '' then
  begin
    Lines[Count] := 'hardwareProfile=' + HwJsonPath; Count := Count + 1;
  end;

  SetArrayLength(Lines, Count);
  if not SaveStringsToFile(AnswerPath, Lines, False) then
    Log('could not write the setup answer file to ' + AnswerPath);

  Args := '-AnswerFile "' + AnswerPath + '"';

  if DockerWanted then
    Args := Args + ' -InstallDocker -EnableWsl'
  else if HwScanOk then
    Args := Args + ' -SkipDocker'
  else if WizardIsComponentSelected('docker') then
    { Detection failed but Docker was asked for: let the bootstrap's own scan
      decide, instead of forcing either answer from here. }
    Args := Args + ' -InstallDocker -EnableWsl'
  else
    Args := Args + ' -SkipDocker';

  if DockerWanted and WizardIsComponentSelected('images') then
    Args := Args + ' -BuildImages';

  if WizardIsComponentSelected('node') then
    Args := Args + ' -InstallNode';

  if WizardIsTaskSelected('preferSystemPython') then
    Args := Args + ' -PreferSystemPython';

  if WizardIsTaskSelected('offline') then
    Args := Args + ' -OfflineOnly';

  if not WizardIsTaskSelected('desktopicon') then
    Args := Args + ' -SkipShortcut';

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

  { Read the recorded installation before any page is built, so the directory
    page can be skipped and DefaultDirName can point at it. }
  DetectExistingInstall();
  if ExistingPath <> '' then
  begin
    if ExistingVer = '{#AppVersion}' then
    begin
      if MsgBox('RedSight {#AppVersion} is already installed at:' + #13#10#13#10 +
                '    ' + ExistingPath + #13#10#13#10 +
                'Only one installation is allowed per computer, so setup will reinstall ' +
                'over it and re-run dependency setup. Continue?',
                mbConfirmation, MB_YESNO) <> IDYES then
      begin
        Result := False;
        Exit;
      end;
    end
    else
      Log('upgrading the installation at ' + ExistingPath +
          ' from version "' + ExistingVer + '" to {#AppVersion}');
  end;

  if not IsAdminInstallMode then
  begin
    MsgBox('RedSight setup must be run as Administrator.' + #13#10#13#10 +
           'It installs Docker Desktop, enables the WSL2 Windows features and ' +
           'writes to Program Files. Right-click the installer and choose ' +
           '"Run as administrator".', mbCriticalError, MB_OK);
    Result := False;
    Exit;
  end;

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
    { Belt and braces: the bootstrap erases the answer file itself, but if it
      never ran, the key must not be left behind in the temp directory. }
    if (AnswerPath <> '') and FileExists(AnswerPath) then
    begin
      DeleteFile(AnswerPath);
      Log('removed a leftover setup answer file');
    end;

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
