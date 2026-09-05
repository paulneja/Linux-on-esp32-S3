Hi, Welcome to Linux on esp32-S3 !!!

Your personal files live in /home/root and survive reboots.
Edit the website in /home/www/index.html and /home/www/cgi-bin/.
Enable it with: web-server on

Create a user with a private home:
  adduser -s /usr/bin/user-shell alice
Switch users with: su - alice
Change your password with: passwd

Background task (survives logout, not power loss or reset):
  nohup micropython /home/root/task.py > /home/root/task.log 2>&1 < /dev/null &

Persistent terminal sessions (when dtach is installed):
  session work
Detach with Ctrl-]. Reattach with: session work
List sessions with: session list

This experimental NOMMU system enforces Unix file permissions, but has no
hardware memory isolation. Do not run untrusted programs or expose it to
untrusted networks. Never give ordinary users write access to system files.
