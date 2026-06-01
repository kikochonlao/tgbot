$src = Join-Path $PSScriptRoot "start_bot.vbs"
$dst = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup\tgbot.vbs"
Copy-Item -Path $src -Destination $dst -Force
Write-Host "Автозагрузка установлена!"
Write-Host "Бот будет запускаться при входе в Windows (скрыто)."
Write-Host "Путь: $dst"
