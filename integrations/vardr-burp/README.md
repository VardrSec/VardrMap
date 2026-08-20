# VardrBurp

Java 21 Montoya extension for deliberately promoting selected Burp HTTP exchanges into an engagement's VardrMap API Surface. It never passively records Proxy traffic.

Build with `gradle jar`, then load `build/libs/vardr-burp-0.1.0.jar` as a Java extension in Burp. In the VardrMap suite tab, enter the backend URL, engagement ID, a full-scope `vmap_` API key, an identity label, and the originating Burp tool. The key stays in memory and is not persisted to the Burp project.

Right-click one or more requests or request/responses in Burp and choose **Send to VardrMap API Surface**. Each selected exchange is promoted separately with its response content type. Credentials are redacted locally and again by VardrMap before storage.
