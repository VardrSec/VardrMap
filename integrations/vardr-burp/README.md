# VardrBurp

Java 21 Montoya extension for deliberately promoting selected Burp HTTP exchanges into an engagement's VardrMap API Surface. It never passively records Proxy traffic.

Build with `gradle jar`, then load `build/libs/vardr-burp-0.1.0.jar` as a Java extension in Burp. In the VardrMap suite tab, enter the backend URL, engagement ID, a full-scope `vmap_` API key, and an identity label. The key stays in memory and is not persisted to the Burp project.

Right-click a request or request/response in Burp and choose **Send to VardrMap API Surface**. Credentials are redacted locally and again by VardrMap before storage.
