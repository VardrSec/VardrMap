package app.vardrmap.burp;

import burp.api.montoya.BurpExtension;
import burp.api.montoya.MontoyaApi;
import burp.api.montoya.http.message.HttpRequestResponse;
import burp.api.montoya.ui.contextmenu.ContextMenuEvent;
import burp.api.montoya.ui.contextmenu.ContextMenuItemsProvider;
import com.google.gson.Gson;

import javax.swing.*;
import java.awt.*;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/** Manual-promotion bridge from Burp to VardrMap's engagement API surface. */
public final class VardrBurpExtension implements BurpExtension, ContextMenuItemsProvider {
    private MontoyaApi api;
    private final JTextField baseUrl = new JTextField("http://127.0.0.1:8000", 32);
    private final JTextField engagementId = new JTextField(32);
    private final JPasswordField apiKey = new JPasswordField(32);
    private final JTextField identityLabel = new JTextField("anonymous", 20);
    private final JLabel status = new JLabel("Not configured");
    private final Gson gson = new Gson();
    private final HttpClient http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(10)).build();

    @Override
    public void initialize(MontoyaApi api) {
        this.api = api;
        api.extension().setName("VardrMap API Surface");
        api.userInterface().registerSuiteTab("VardrMap", buildPanel());
        api.userInterface().registerContextMenuItemsProvider(this);
        api.logging().logToOutput("VardrMap loaded. Automatic capture is disabled; use Send to VardrMap explicitly.");
    }

    private Component buildPanel() {
        JPanel form = new JPanel(new GridBagLayout());
        GridBagConstraints c = new GridBagConstraints();
        c.insets = new Insets(6, 8, 6, 8); c.anchor = GridBagConstraints.WEST; c.fill = GridBagConstraints.HORIZONTAL;
        addRow(form, c, 0, "VardrMap URL", baseUrl);
        addRow(form, c, 1, "Engagement ID", engagementId);
        addRow(form, c, 2, "Full-scope API key", apiKey);
        addRow(form, c, 3, "Identity label", identityLabel);
        c.gridx = 1; c.gridy = 4; form.add(status, c);
        JTextArea notice = new JTextArea("Credentials are held in memory only and are not saved in the Burp project.\nSelected messages are redacted locally, then redacted again by VardrMap before storage.");
        notice.setEditable(false); notice.setOpaque(false); notice.setLineWrap(true); notice.setWrapStyleWord(true);
        c.gridy = 5; c.weightx = 1; form.add(notice, c);
        JPanel wrapper = new JPanel(new BorderLayout()); wrapper.add(form, BorderLayout.NORTH);
        return wrapper;
    }

    private void addRow(JPanel panel, GridBagConstraints c, int row, String label, JComponent field) {
        c.gridy = row; c.gridx = 0; c.weightx = 0; panel.add(new JLabel(label), c);
        c.gridx = 1; c.weightx = 1; panel.add(field, c);
    }

    @Override
    public List<Component> provideMenuItems(ContextMenuEvent event) {
        HttpRequestResponse selected = event.messageEditorRequestResponse()
                .map(editor -> editor.requestResponse())
                .orElseGet(() -> event.selectedRequestResponses().isEmpty() ? null : event.selectedRequestResponses().get(0));
        if (selected == null) return null;
        JMenuItem send = new JMenuItem("Send to VardrMap API Surface");
        send.addActionListener(ignored -> submit(selected));
        List<Component> items = new ArrayList<>(); items.add(send); return items;
    }

    private void submit(HttpRequestResponse exchange) {
        String key = new String(apiKey.getPassword());
        String engagement = engagementId.getText().trim();
        if (key.isBlank() || engagement.isBlank()) {
            status.setText("Set an engagement ID and API key first");
            return;
        }
        status.setText("Sending selected exchange…");
        try {
            var request = exchange.request();
            var response = exchange.response();
            Map<String, Object> payload = new HashMap<>();
            payload.put("method", request.method());
            payload.put("url", request.url());
            payload.put("source_tool", "unknown");
            payload.put("identity_label", identityLabel.getText().trim().isBlank() ? "anonymous" : identityLabel.getText().trim());
            payload.put("request_headers", LocalRedactor.redact(String.join("\n", request.headers().stream().map(Object::toString).toList())));
            payload.put("request_body", LocalRedactor.redact(request.bodyToString()));
            if (response != null) {
                payload.put("response_headers", LocalRedactor.redact(String.join("\n", response.headers().stream().map(Object::toString).toList())));
                payload.put("response_body", LocalRedactor.redact(response.bodyToString()));
                payload.put("response_status", response.statusCode());
                payload.put("response_length", response.body().length());
            }
            URI target = URI.create(baseUrl.getText().trim().replaceAll("/+$", "") + "/engagements/" + engagement + "/api/exchanges");
            HttpRequest outgoing = HttpRequest.newBuilder(target).timeout(Duration.ofSeconds(20))
                    .header("Authorization", "Bearer " + key).header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString(gson.toJson(payload))).build();
            http.sendAsync(outgoing, HttpResponse.BodyHandlers.ofString()).whenComplete((result, error) -> SwingUtilities.invokeLater(() -> {
                if (error != null) {
                    status.setText("Send failed: " + error.getMessage());
                    api.logging().logToError("VardrMap send failed", error);
                } else if (result.statusCode() >= 200 && result.statusCode() < 300) {
                    status.setText("Promoted successfully");
                } else {
                    status.setText("VardrMap returned HTTP " + result.statusCode());
                    api.logging().logToError("VardrMap returned " + result.statusCode() + ": " + result.body());
                }
            }));
        } catch (RuntimeException error) {
            status.setText("Invalid configuration or message");
            api.logging().logToError("VardrMap send failed", error);
        }
    }
}
