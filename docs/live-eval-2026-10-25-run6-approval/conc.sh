#!/bin/bash
# 5 rounds of 2 simultaneous SMS inbounds (F9 question, distinct numbers) to the main throwaway server.
WH=evalwebhooktoken-0123456789abcdef
for round in 1 2 3 4 5; do
  for k in 1 2; do
    n=$((round*10+k))
    curl -s -o /dev/null -w "round $round from +2332410000$n http %{http_code}\n" -X POST 127.0.0.1:18080/channels/sms/inbound/$WH \
      --data-urlencode "from=+2332410000$n" --data-urlencode "text=What is the cocoa producer price this season?" \
      --data-urlencode "id=ATconc-$n" --data-urlencode "to=12345" &
  done
  wait; sleep 25
done
