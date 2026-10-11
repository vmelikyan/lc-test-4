const express = require('express');
const grpc = require('@grpc/grpc-js');
const protoLoader = require('@grpc/proto-loader');

const app = express();
const port = 8080;

const packageDefinition = protoLoader.loadSync(__dirname + '/echo-me.proto', {
    keepCase: true,
    longs: String,
    enums: String,
    defaults: true,
    oneofs: true
});

const echo_proto = grpc.loadPackageDefinition(packageDefinition).simple;
const client = new echo_proto.SimpleService(process.env.CLIENT_HOST, grpc.credentials.createInsecure());

app.get('/', (req, res) => {
    res.send(`Hello from express app: CLIENT_HOST: ${process.env.CLIENT_HOST}`);
});

app.get('/echo', (req, res) => {
    let message = req.query.message || "You did not specify a message!";

    client.Echo({ value: message }, function(err, response) {
        if (err) {
            res.send('Error: ' + err.message);
        } else {
            res.send('Received from gRPC server: ' + response.value);
        }
    });
});

app.get('/__lbheartbeat__', (req, res) => {
    res.send('beating heart');
});

app.listen(port, () => {
    console.log(`App running on http://localhost:${port}`);
});
// e2e C2
// e2e C3
// e2e C4
// e2e C5
// e2e Y6
// e2e Y7
// e2e Y8
// e2e Y9
// e2e T1
// e2e T3
// e2e T4
// e2e T5
// e2e T6
