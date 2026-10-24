param([string]$Pythonw, [string]$AppDir)
$shell = New-Object -ComObject WScript.Shell
$targets = @([Environment]::GetFolderPath('Desktop'), (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'))
foreach ($dir in $targets) {
  # the app used to be called Inkwell: remove the old shortcut
  $old = Join-Path $dir 'Inkwell.lnk'
  if (Test-Path $old) { Remove-Item $old -Force }
  $lnk = $shell.CreateShortcut((Join-Path $dir "Babel's Library.lnk"))
  $lnk.TargetPath = $Pythonw
  $lnk.Arguments = '"' + (Join-Path $AppDir 'app\desktop.py') + '"'
  $lnk.WorkingDirectory = $AppDir
  $lnk.IconLocation = (Join-Path $AppDir 'app\static\icon.ico')
  $lnk.Description = "Babel's Library"
  $lnk.Save()
}
