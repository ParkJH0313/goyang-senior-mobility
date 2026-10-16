class ChatError extends Error {
  constructor(code,message,status=502){super(message);this.code=code;this.status=status;}
}
module.exports={ChatError};
