# Demo

```sh
python3 app.py --db /tmp/crm-demo.sqlite3 --user demo add 'Anna Example' --email anna@example.test --org ExampleCo
python3 app.py --db /tmp/crm-demo.sqlite3 --user demo interaction 1 'Discussed the project timeline'
python3 app.py --db /tmp/crm-demo.sqlite3 --user demo followup 1 2026-11-02 'Share the timeline'
python3 app.py --db /tmp/crm-demo.sqlite3 --user demo today
python3 app.py --db /tmp/crm-demo.sqlite3 --user demo done 1
python3 app.py --db /tmp/crm-demo.sqlite3 --user demo today
python3 app.py --db /tmp/crm-demo.sqlite3 --user other search Anna
python3 app.py --db /tmp/crm-demo.sqlite3 --user demo export /tmp/crm-demo.csv
```

`today` prints the follow-up ID so it can be completed with `done FOLLOWUP_ID`; the second `today` no longer lists it. The second owner sees no contact. All names and data are synthetic.
