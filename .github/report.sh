#!/bin/sh
# Publie la fin d'un journal comme annotation d'erreur GitHub : report.sh "titre" fichier [lignes]
title="$1"; file="$2"; n="${3:-80}"
[ -f "$file" ] || exit 0
msg=$(tail -n "$n" "$file" | sed -e 's/%/%25/g' -e 's/\r/%0D/g' | awk 'BEGIN{ORS="%0A"}{print}')
echo "::error title=$title::$msg"
