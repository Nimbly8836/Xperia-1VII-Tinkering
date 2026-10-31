#!/data/data/com.termux/files/usr/bin/bash
# Termux:Widget shortcut. Sends immediately; no preview or device validation.
printf "Requesting SIM mode: dual physical SIM\n"
RISH_APPLICATION_ID=com.termux RISH_PRESERVE_ENV=0 /system/bin/sh "$HOME/.local/share/xperia-rish/rish" -c '/system/bin/am broadcast --user 0 --receiver-foreground --receiver-permission android.permission.READ_PRIVILEGED_PHONE_STATE -a com.android.euicc.service.SIM_TYPE_UPDATE_ACTION -p com.qti.phone --ei com.android.euicc.service.extra_sim_type 0'
result=$?
printf "\nCommand finished with exit code: %s. Check the SIM status in Settings.\n" "$result"
read -r -p "Press Enter to close this window..." _
exit "$result"
