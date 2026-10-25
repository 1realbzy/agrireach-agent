#!/bin/bash
# 2 rounds of 2 simultaneous SMS inbounds with the F1 question (the pair that failed in run 5's first attempt).
WH=evalwebhooktoken-0123456789abcdef
Q="Adaklu maize farmer planted late Feb, saw worms mid-March, sprayed the recommended chemicals with no effect. What next?"
for round in 6 7; do
  for k in 1 2; do
    n=$((round*10+k))
    curl -s -o /dev/null -w "round $round from +2332410000$n http %{http_code}\n" -X POST 127.0.0.1:18080/channels/sms/inbound/$WH \
      --data-urlencode "from=+2332410000$n" --data-urlencode "text=$Q" --data-urlencode "id=ATconc-$n" --data-urlencode "to=12345" &
  done
  wait; sleep 50
done
