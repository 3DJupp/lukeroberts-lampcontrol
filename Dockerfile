ARG BUILD_FROM
FROM $BUILD_FROM

# dbus needed so bleak can reach the host BlueZ via the D-Bus socket
RUN apk add --no-cache dbus

WORKDIR /app
COPY src/requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY src/ .
COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD ["/run.sh"]
