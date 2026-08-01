!#/bin/bash

if [ $# -eq 0 ]; then
  echo "Usage: $0 \"commit message\""
  exit 1
fi

git add .
git commit -m "$1"
git push origin Testing
