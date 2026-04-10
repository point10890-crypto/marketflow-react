$base = "https://nonalliterated-sunshine-unaffiliated.ngrok-free.dev"
$h = @{"ngrok-skip-browser-warning"="1"}
$cf = "$env:USERPROFILE\.cloudflared"
mkdir $cf -Force | Out-Null

Write-Host "1/4 .env"
iwr "$base/.env" -Headers $h -OutFile "C:\bitman_marketfloww\.env"
Write-Host "2/4 config.yml"
iwr "$base/cloudflared_config.yml" -Headers $h -OutFile "$cf\config.yml"
Write-Host "3/4 cred.json"
iwr "$base/cloudflared_cred.json" -Headers $h -OutFile "$cf\678e9c60-9f8d-4f49-9fba-a49400ef4ca0.json"
Write-Host "4/4 data (55MB)..."
iwr "$base/marketflow_data.tar.gz" -Headers $h -OutFile "C:\bitman_marketfloww\marketflow_data.tar.gz"
cd C:\bitman_marketfloww
tar xzf marketflow_data.tar.gz
Write-Host "DONE!" -ForegroundColor Green
