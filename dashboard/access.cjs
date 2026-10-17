// Access and carbon share one implementation in browser and server.
const {evaluate,boardingTime,waitMinutes}=require('./dist/model.js');
module.exports={evaluate,boardingTime,waitMinutes};
