# Context for rfc8446 §4.6.3 (Key and Initialization Vector Update)

---

## rfc8446 §4.6.3 — Key and Initialization Vector Update [target]

4.6.3.  Key and Initialization Vector Update

   The KeyUpdate handshake message is used to indicate that the sender
   is updating its sending cryptographic keys.  This message can be sent
   by either peer after it has sent a Finished message.  Implementations
   that receive a KeyUpdate message prior to receiving a Finished
   message MUST terminate the connection with an "unexpected_message"
   alert.

      enum {
          update_not_requested(0), update_requested(1), (255)
      } KeyUpdateRequest;

      struct {
          KeyUpdateRequest request_update;
      } KeyUpdate;

   request_update:  Indicates whether the recipient of the KeyUpdate
      should respond with its own KeyUpdate.  If an implementation
      receives any other value, it MUST terminate the connection with an
      "illegal_parameter" alert.

   If the request_update field is set to "update_requested", then the
   receiver MUST send a KeyUpdate of its own with request_update set to
   "update_not_requested" prior to sending its next Application Data
   record.  This mechanism allows either side to force an update to the
   entire connection, but causes an implementation which receives
   multiple KeyUpdates while it is silent to respond with a single
   update.

   Note that implementations may receive an arbitrary number of messages
   between sending a KeyUpdate with request_update set to
   "update_requested" and receiving the peer's KeyUpdate, because those
   messages may already be in flight.

   If implementations independently send their own KeyUpdates with
   request_update set to "update_requested" and they cross in flight,
   then each side will also send a response, with the result that each
   side increments by two generations.

   Both sender and receiver MUST encrypt their KeyUpdate messages with
   the old keys.  Additionally, both sides MUST enforce that a KeyUpdate
   with the old key is received before accepting any messages encrypted
   with the new key.

   After sending a KeyUpdate message, the sender SHALL send all its
   traffic using the next generation of keys.
