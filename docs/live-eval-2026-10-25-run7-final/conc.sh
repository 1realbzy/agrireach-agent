#!/bin/bash
# 10 pairs of simultaneous SMS inbounds to the main throwaway server: pairs 1-7 the F9 question, 8-10 the F1 question.
WH=evalwebhooktoken-0123456789abcdef
F9="What is the cocoa producer price this season?"
F1="Adaklu maize farmer planted late Feb, saw worms mid-March, sprayed the recommended chemicals with no effect. What next?"
for round in 1 2 3 4 5 6 7 8 9 10; do
  if [ $round -le 7 ]; then Q="$F9"; S=20; else Q="$F1"; S=55; fi
  for k in 1 2; do
    n=$(printf "%02d%d" $round $k)
    curl -s -o /dev/null -w "pair $round from +23324200$n http %{http_code}\n" -X POST 127.0.0.1:18080/channels/sms/inbound/$WH \
      --data-urlencode "from=+23324200$n" --data-urlencode "text=$Q" --data-urlencode "id=ATconc-$n" --data-urlencode "to=12345" &
  done
  wait; sleep $S
done
