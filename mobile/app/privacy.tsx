import React from "react";
import { View, Text, ScrollView, TouchableOpacity, StyleSheet } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";

export default function PrivacyPolicyScreen() {
  const router = useRouter();

  return (
    <SafeAreaView style={styles.container} edges={["top", "left", "right"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}>
          <Text style={styles.back}>← Back</Text>
        </TouchableOpacity>
        <Text style={styles.title}>Privacy Policy</Text>
      </View>

      <ScrollView contentContainerStyle={styles.body} showsVerticalScrollIndicator={false}>
        <Text style={styles.updated}>Last updated: June 25, 2026</Text>

        <Section title="1. What We Collect">
          When you use GradGPS, we collect:{"\n\n"}
          • Your name and a user identifier created at sign-up{"\n"}
          • Your selected major and subplan{"\n"}
          • Academic data from your uploaded transcript: course codes, grades, credits earned, and enrollment terms{"\n\n"}
          We do not collect your Google or Apple account password, Social Security Number, financial information, or any data beyond what is needed to provide the degree-planning service.
        </Section>

        <Section title="2. How We Use Your Information">
          Your data is used exclusively to:{"\n\n"}
          • Generate your personalized degree audit and academic timeline{"\n"}
          • Show your credit progress toward graduation{"\n"}
          • Recommend future courses based on your remaining requirements{"\n\n"}
          We do not sell, rent, or share your personal information with third parties for marketing purposes.
        </Section>

        <Section title="3. Third-Party Services">
          GradGPS uses the following external services:{"\n\n"}
          • Professor Ratings — When you tap a course, we retrieve professor ratings using the course code only (no personal data).{"\n"}
          • University Course Bulletins — We fetch public course descriptions using the course code only.{"\n\n"}
          No personally identifiable information is sent to either of these services. As GradGPS expands to support additional schools, new institution-specific integrations may be added. Any such additions will be reflected in an updated Privacy Policy.
        </Section>

        <Section title="4. Data Storage">
          Your profile and transcript data are stored securely in cloud databases (AWS DynamoDB). Transcript PDF files, if retained, are stored in encrypted object storage (AWS S3). Access is restricted to the GradGPS application.
        </Section>

        <Section title="5. Data Retention">
          Your data is retained for as long as your account is active. You may request deletion of your account and all associated data at any time by contacting us. Upon deletion, your transcript data, profile, and academic records will be permanently removed.
        </Section>

        <Section title="6. Security">
          We take reasonable measures to protect your data, including encrypted storage and access controls. However, no system is completely secure. Please do not share your account credentials with others.
        </Section>

        <Section title="7. Children's Privacy">
          GradGPS is intended for use by college students (18+). We do not knowingly collect data from anyone under 13 years of age.
        </Section>

        <Section title="8. Changes to This Policy">
          We may update this Privacy Policy from time to time. We will notify you of material changes through the app. Continued use after changes are posted means you accept the updated policy.
        </Section>

        <Section title="9. Contact Us">
          If you have questions or want to request data deletion, contact us at support@gradgps.app.
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
