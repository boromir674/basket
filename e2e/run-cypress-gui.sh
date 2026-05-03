# wrapper script around dockerized cypress service to connect to host X server

# ommit authentication step to connect to the X Server; allow anyone to connect
xhost +

# INTERACTIVE CYPRESS
# To start in the interactive mode we need to pass both filenames to the docker

docker-compose -f e2e/docker-compose.yml -f e2e/cy-open.yml up --build --exit-code-from cypress

xhost -
