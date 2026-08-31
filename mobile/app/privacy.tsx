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
        <Text style={styles.updated}>Last updated: August 30, 2026</Text>

        <Section title="1. Who We Are">
          GradGPS is an independent planning tool operated by Matthew Krokosz, an individual developer based in the United States (the "we," "us," or "operator" referred to in this policy). You can reach us at support@gradgps.com or through the Contact Support screen in the app.{"\n\n"}
          GradGPS is a student-built tool and is not affiliated with, endorsed by, or sponsored by The Pennsylvania State University. It is not official academic advising. Course and program information comes from publicly available university sources, and "Penn State" and related names are the property of their respective owners.
        </Section>

        <Section title="2. What We Collect">
          When you use GradGPS, we collect:{"\n\n"}
          • Your name and email address, provided by your sign-in method (Google, Apple, or email verification code), and a user identifier created at sign-up{"\n"}
          • Your selected major and subplan{"\n"}
          • Basic account activity information, such as when you signed up and when you last used the app{"\n"}
          • Academic data parsed from your uploaded transcript: course codes, grades, credits earned, and enrollment terms{"\n"}
          • A copy of the transcript PDF you upload, and — if you upload an official transcript — the date you acknowledged and consented to using it{"\n\n"}
          We recommend uploading your unofficial transcript. An official transcript PDF may also carry your name and Penn State student ID number as printed on the document. We only extract and use the academic data listed above. We never ask you for, and never store, your account password, your Social Security Number, or any financial information.
        </Section>

        <Section title="3. How We Use Your Information">
          Your data is used exclusively to:{"\n\n"}
          • Generate your personalized degree audit and academic timeline{"\n"}
          • Show your credit progress toward graduation{"\n"}
          • Recommend future courses based on your remaining requirements{"\n"}
          • Sign you in and keep your account secure{"\n"}
          • Respond when you contact support{"\n"}
          • Review anonymized, aggregate counts (such as total sign-ups) to improve GradGPS{"\n\n"}
          We do not sell or rent your personal information, and we do not share it with third parties for advertising or marketing. GradGPS uses no third-party analytics, advertising, or cross-site tracking services.{"\n\n"}
          GradGPS builds your audit and timeline through our own matching against published university requirements. We do not send your personal data to third-party AI services, and we never use your data to train AI models.
        </Section>

        <Section title="4. Third-Party Services">
          GradGPS uses the following external services:{"\n\n"}
          • Sign-In Providers — If you sign in with Google or Apple, they handle authentication and share your name and email address with us. Their own privacy policies apply to your use of those services.{"\n"}
          • Email Delivery — We use Amazon Web Services to send emails such as sign-in verification codes and replies to your support requests.{"\n"}
          • Professor Ratings — When you tap a course, we retrieve professor ratings using the course code only (no personal data).{"\n"}
          • University Course Bulletins — We fetch public course descriptions using the course code only.{"\n\n"}
          No personally identifiable information is sent to the professor-ratings or course-bulletin services. As GradGPS expands to support additional schools, new institution-specific integrations may be added. Any such additions will be reflected in an updated Privacy Policy.
        </Section>

        <Section title="5. Data Storage">
          Your profile and transcript data are stored securely in cloud databases (AWS DynamoDB). Uploaded transcript PDF files — whether unofficial or official — are stored in encrypted object storage (AWS S3). Access is restricted to the GradGPS application. Deleting your transcript in the app removes the stored PDF and its parsed course data.
        </Section>

        <Section title="6. Data Retention">
          We retain your data while your account is active. If you do not use GradGPS for 24 consecutive months, we may delete your account and its associated data. You can permanently delete your account and all associated data at any time from the Account screen in the app — this removes your transcript file, parsed academic data, profile, and active sessions. You may also request deletion by contacting us.
        </Section>

        <Section title="7. Your Rights & Choices">
          You can, at any time:{"\n\n"}
          • Access the profile and academic data we hold, viewable directly in the app{"\n"}
          • Correct or update your major, subplan, and in-progress classes in the app, or re-upload a transcript{"\n"}
          • Delete your transcript, or your entire account and all associated data, from the Account screen{"\n"}
          • Request a copy of your data, or ask us any privacy question, by contacting us{"\n\n"}
          We do not sell your personal information and have not done so. Because GradGPS does not track you across other websites or over time, we do not respond differently to browser "Do Not Track" signals.
        </Section>

        <Section title="8. Security">
          We take reasonable measures to protect your data, including encrypted storage and access controls. However, no system is completely secure. Please keep the sign-in method associated with your account (your Google, Apple, or email account) secure and do not share it with others.
        </Section>

        <Section title="9. Children's Privacy">
          GradGPS is intended for current and prospective college students and is not directed at children. We do not knowingly collect data from anyone under 13 years of age. If you believe a child under 13 has provided us data, contact us and we will delete it.
        </Section>

        <Section title="10. Changes to This Policy">
          We may update this Privacy Policy from time to time. We will notify you of material changes through the app. Continued use after changes are posted means you accept the updated policy.
        </Section>

        <Section title="11. Contact Us">
          If you have questions or want to request data deletion, contact us at support@gradgps.com or through the Contact Support screen in the app.
        </Section>
      </ScrollView>
    </SafeAreaView>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
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
