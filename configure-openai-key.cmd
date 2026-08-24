@echo off
setlocal
echo Learn With Stories - OpenAI API key setup
echo.
echo The key will be saved in your Windows user environment as OPENAI_API_KEY.
echo It will not be written to settings.json or displayed on screen.
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$secure=Read-Host 'Paste a newly created OpenAI Platform API key' -AsSecureString; $ptr=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure); try{$key=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr).Trim(); if($key.StartsWith('Bearer ',[StringComparison]::OrdinalIgnoreCase)){$key=$key.Substring(7).Trim()}; $key=$key.Trim([char]34,[char]39); if($key -cnotmatch '^sk-[A-Za-z0-9_-]+$'){throw 'The pasted value contains altered or non-ASCII characters. Create a new key and use the Copy button on platform.openai.com/api-keys; do not copy it through chat, Word, translated pages, or formatted documents.'}; [Environment]::SetEnvironmentVariable('OPENAI_API_KEY',$key,'User'); $saved=[Environment]::GetEnvironmentVariable('OPENAI_API_KEY','User'); if($saved -cne $key){throw 'Windows did not persist the key exactly.'}; Write-Host 'API key saved and verified. Close every Learn With Stories window, then start it again.' -ForegroundColor Green} catch{Write-Host $_.Exception.Message -ForegroundColor Red; exit 1} finally{if($ptr -ne [IntPtr]::Zero){[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)}}"
echo.
pause
