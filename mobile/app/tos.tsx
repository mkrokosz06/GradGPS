import React from "react";
import { View, Text, ScrollView, TouchableOpacity, StyleSheet } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";

export default function TermsOfServiceScreen() {
  const router = useRouter();

  return (
    <SafeAreaView style={styles.container} edges={["top", "left", "right"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}>
          <Text style={styles.back}>← Back</Text>
        </TouchableOpacity>
        <Text style={styles.title}>Terms of Service</Text>
      </View>

      <ScrollView contentContainerStyle={styles.body} showsVerticalScrollIndicator={false}>
        <Text style={styles.updated}>Last updated: June 25, 2026</Text>

        <Section title="1. Acceptance of Terms">
          By using GradGPS, you agree to these Terms of Service. If you do not agree, please do not use the app.
        </Section>

        <Section title="2. Description of Service">
          GradGPS is an academic planning tool that helps college students track their degree progress, visualize their academic timeline, and explore professor ratings. It is a student-built tool and is provided free of charge during its beta period.
        </Section>

        <Section title="3. Not Official Academic Advising">
          GradGPS is not affiliated with, endorsed by, or sponsored by any college or university. The information provided is for planning purposes only and does not constitute official academic advising. Always verify your degree requirements and progress with your official academic advisor and through your institution's official systems.
        </Section>

        <Section title="4. Accuracy of Information">
          While we strive to keep degree requirement data accurate, GradGPS makes no guarantees about the completeness or accuracy of any information displayed. Requirement data is sourced from publicly available course catalogs and may not reflect your specific academic contract or catalog year.
        </Section>

        <Section title="5. Your Responsibilities">
          You are responsible for the accuracy of any transcript or personal information you upload. You agree not to misuse, reverse-engineer, or attempt to disrupt the service. You must be a currently enrolled or prospective college student to use this app.
        </Section>

        <Section title="6. Transcript Data">
          You may upload an unofficial transcript PDF to GradGPS. By doing so, you grant us permission to parse and store the academic data contained in that transcript (course codes, grades, credits, and enrollment terms) solely for the purpose of providing the GradGPS service to you.
        </Section>

        <Section title="7. Limitation of Liability">
          GradGPS is provided "as is" without warranty of any kind. We are not liable for any decisions made based on information displayed in the app, including but not limited to course registration, major changes, or graduation planning.
        </Section>

        <Section title="8. Changes to Terms">
          We may update these terms at any time. Continued use of the app after changes are posted constitutes acceptance of the revised terms.
        </Section>

        <Section title="9. Contact">
          Questions about these terms? Reach out at support@gradgps.app.
        </Section>
      </ScrollView>
    </SafeAreaView>
  );
}

function Section({ title, children }: { title: string; children: string }) {
  return (
    <View style={{ marginBottom: 24 }}>
      <Text style={styles.sectionTitle}>{title}</Text>
      <Text style={styles.sectionBody}>{children}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#ffffff" },
  header: {
    paddingHorizontal: 20, paddingTop: 16, paddingBottom: 14,
    borderBottomWidth: 1, borderBottomColor: "#f1f5f9",
  },
  back:  { color: "#2a5298", fontSize: 14, marginBottom: 10 },
  title: { color: "#1a3a6b", fontSize: 22, fontWeight: "700" },
  body:  { paddingHorizontal: 24, paddingTop: 20, paddingBottom: 60 },
  updated: { color: "#94a3b8", fontSize: 12, marginBottom: 28 },
  sectionTitle: { color: "#1e293b", fontSize: 15, fontWeight: "700", marginBottom: 6 },
  sectionBody:  { color: "#475569", fontSize: 14, lineHeight: 22 },
});
