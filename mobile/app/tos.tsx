import React from "react";
import { View, Text, ScrollView, TouchableOpacity, StyleSheet } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useRouter } from "expo-router";

export default function TermsOfUseScreen() {
  const router = useRouter();

  return (
    <SafeAreaView style={styles.container} edges={["top", "left", "right"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}>
          <Text style={styles.back}>← Back</Text>
        </TouchableOpacity>
        <Text style={styles.title}>Terms of Use</Text>
      </View>

      <ScrollView contentContainerStyle={styles.body} showsVerticalScrollIndicator={false}>
        <Text style={styles.updated}>Last updated: September 21, 2026</Text>

        <Callout>
          <Text style={styles.calloutStrong}>The short version.</Text> GradGPS is a free planning tool built by a student. It is not official academic advising and it is not always right. Use it to prepare for your advising appointment, not to replace it. Your degree is your responsibility, and the university's own records are the ones that count.
        </Callout>

        <Section title="1. Who these terms are between">
          These Terms of Use govern your use of the GradGPS mobile application and the gradgps.com website (together, the "Service"), operated by Matthew Krokosz, an individual developer in the United States ("we," "us"). By using the Service you agree to these terms. If you don't agree, don't use it.
        </Section>

        <Section title="2. Not affiliated with Penn State">
          GradGPS is an independent student project. It is not affiliated with, endorsed by, sponsored by, or approved by The Pennsylvania State University. Course, program, and requirement information is drawn from publicly published university sources. "Penn State," "LionPATH," and related names and marks belong to their respective owners and are used here only to describe what the Service does.
        </Section>

        <Section title="3. Not academic advice">
          The Service produces an estimate of your degree progress and a suggested course schedule. It is a planning aid, not academic, financial, legal, or professional advice. Specifically:{"\n\n"}
          • Requirements change, and our copy of the catalog may be out of date or incorrect.{"\n"}
          • Departments grant exceptions, substitutions, and waivers that no published catalog records.{"\n"}
          • Course availability, prerequisites, and offering terms can differ from what is scheduled.{"\n"}
          • Your official degree audit and your academic adviser are authoritative. This is not.{"\n\n"}
          Always confirm your plan with your academic adviser before registering. We do not guarantee that following a GradGPS plan will result in graduation, in any particular timeframe or at all.
        </Section>

        <Section title="4. Who can use the Service">
          GradGPS is built for current and prospective college students. You must be at least 13 years old to use the Service. If you are under 18, you may use it only with the consent of a parent or guardian, who accepts these terms on your behalf. We don't knowingly collect data from anyone under 13 — if you believe we have, contact us and we will delete it.
        </Section>

        <Section title="5. Your account and your data">
          You are responsible for the accuracy of what you upload and for keeping your sign-in method secure. Don't upload anyone else's transcript or academic record. You may delete your transcript, or your entire account and all associated data, at any time from the Account screen in the app. How we handle your data is described in the Privacy Policy, which you can open from the menu in the app, and which forms part of these terms.
        </Section>

        <Section title="6. Acceptable use">
          You agree not to:{"\n\n"}
          • Scrape, bulk-download, resell, or redistribute data from the Service.{"\n"}
          • Attempt to access another user's account, data, or audit.{"\n"}
          • Interfere with, overload, probe, or reverse-engineer the Service or its infrastructure.{"\n"}
          • Use the Service to violate any law or any policy of your institution.{"\n"}
          • Upload malicious files or content you don't have the right to upload.
        </Section>

        <Section title="7. Beta software">
          The Service is distributed as a beta through Apple TestFlight. It is under active development, may be unavailable, may lose data, and may change or be discontinued at any time without notice. Features described on the GradGPS website may not be present in the build you install.
        </Section>

        <Section title="8. No warranty">
          The Service is provided "as is" and "as available," without warranties of any kind, whether express or implied, including without limitation any implied warranties of merchantability, fitness for a particular purpose, accuracy, or non-infringement. We do not warrant that the Service will be uninterrupted, secure, error-free, or that any information it produces is accurate or complete.
        </Section>

        <Section title="9. Limitation of liability">
          To the maximum extent permitted by law, we will not be liable for any indirect, incidental, special, consequential, or punitive damages, or for any loss of data, academic standing, tuition, time to degree, financial aid, or opportunity, arising out of or relating to your use of the Service — including any decision you make in reliance on a GradGPS audit or plan. Our total liability for any claim relating to the Service will not exceed US $50.{"\n\n"}
          Some jurisdictions don't allow certain limitations, so parts of this section may not apply to you. Nothing here limits liability that cannot lawfully be limited.
        </Section>

        <Section title="10. Your responsibility for how you use it">
          You agree to indemnify and hold harmless the operator of GradGPS — and anyone working on the Service with us — from any claim, demand, loss, liability, or expense (including reasonable legal fees) brought by a third party and arising out of:{"\n\n"}
          • Your use of the Service, including any decision you make in reliance on an audit or plan.{"\n"}
          • Anything you upload, including a transcript or academic record that isn't yours or that you don't have the right to upload.{"\n"}
          • Your breach of these terms, or of any law or any policy of your institution.{"\n"}
          • Your violation of someone else's rights, including privacy or intellectual-property rights.{"\n\n"}
          We'll tell you promptly about any such claim and won't settle it in a way that creates an obligation for you without your agreement. You may take over the defense with counsel we reasonably approve. This section doesn't apply to the extent a claim results from our own conduct, and nothing in it asks you to cover something the law doesn't allow us to shift to you. It survives the end of your use of the Service.
        </Section>

        <Section title="11. Third-party services">
          The Service relies on and links to third parties, including Apple, Google, Amazon Web Services, and publicly available university course catalogs. We are not responsible for those services, and their own terms apply to your use of them.
        </Section>

        <Section title="12. Copyright complaints">
          We respect copyright. If you believe something on the Service infringes a copyright you own or represent, email support@gradgps.com and tell us what the work is, what you believe is infringing it, where to find that on the Service, and how to reach you. Please confirm that you own the copyright or are authorized to act for the owner.{"\n\n"}
          We'll review the notice and remove or disable anything that shouldn't be there. If your material was removed and you think that was a mistake, email the same address and we'll take another look. We close the accounts of people who repeatedly infringe others' copyrights.{"\n\n"}
          Please use the subject line "Copyright" so the notice is routed correctly. For anything else, use the same address or the Contact Support screen in the app.
        </Section>

        <Section title="13. Termination">
          You may stop using the Service and delete your account at any time. We may suspend or terminate access if you breach these terms or if we discontinue the Service. Sections 3, 8, 9, 10, 14, and 15 survive termination.
        </Section>

        <Section title="14. Governing law">
          These terms are governed by the laws of the Commonwealth of Pennsylvania, without regard to its conflict-of-law rules. Subject to the arbitration agreement in Section 15, you agree to the exclusive jurisdiction of the state and federal courts located in Pennsylvania.
        </Section>

        <Section
          title="15. Disputes, arbitration, and class-action waiver"
          callout={
            <>
              <Text style={styles.calloutStrong}>Read this section.</Text> It changes how disputes between us are resolved. Except for the small claims described below, you and we agree to resolve disputes through <Text style={styles.strong}>individual binding arbitration</Text> rather than in court, and to give up the right to a jury trial and to participate in a class action. <Text style={styles.strong}>You can opt out within 30 days</Text> and nothing else in these terms changes if you do.
            </>
          }
        >
          <Text style={styles.strong}>Talk to us first.</Text> If something goes wrong, email support@gradgps.com, or use the Contact Support screen in the app, with a description of the problem and what you want. We'll try to resolve it informally. Neither of us may start an arbitration until 30 days after that notice.{"\n\n"}
          <Text style={styles.strong}>Arbitration.</Text> If we can't resolve it, any dispute arising out of or relating to these terms or the Service will be settled by binding arbitration administered by the American Arbitration Association under its Consumer Arbitration Rules, before a single arbitrator. The arbitration will take place in Pennsylvania, or by phone or video, or through documents only — your choice. The arbitrator decides the dispute and may award the same individual relief a court could. Judgment on the award may be entered in any court with jurisdiction. This agreement is governed by the Federal Arbitration Act.{"\n\n"}
          <Text style={styles.strong}>Small claims and injunctions are exceptions.</Text> Either of us may bring an individual claim in small-claims court if it qualifies, and either of us may ask a court for an injunction to stop unauthorized use of, or interference with, the Service.{"\n\n"}
          <Text style={styles.strong}>No class actions.</Text> Claims may be brought only in your or our individual capacity, and not as a plaintiff or class member in any class, collective, consolidated, or representative proceeding. The arbitrator may not consolidate claims or preside over any form of representative proceeding. If this paragraph is found unenforceable as to a particular claim or request for relief, that claim or request is severed and goes to court, while the rest stays in arbitration.{"\n\n"}
          <Text style={styles.strong}>How to opt out.</Text> You can opt out of this whole section by emailing support@gradgps.com with the subject line "Arbitration Opt-Out," your name, and the email address on your account, within 30 days of first accepting these terms. Opting out doesn't affect anything else in these terms, and we won't hold it against you. If you opt out, disputes go to the Pennsylvania courts named in Section 14.{"\n\n"}
          If we materially change this section, you may reject the change by emailing us within 30 days of the "last updated" date, and the previous version will keep applying to you.
        </Section>

        <Section title="16. Changes to these terms">
          We may update these terms. Material changes will be noted in the app or on this page, and the "last updated" date above will change. Continuing to use the Service after an update means you accept the revised terms.
        </Section>

        <Section title="17. Contact">
          Questions about these terms: support@gradgps.com, or the Contact Support screen in the app. Copyright complaints go to the address in Section 12.
        </Section>
      </ScrollView>
    </SafeAreaView>
  );
}

function Section({
  title,
  callout,
  children,
}: {
  title: string;
  callout?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <View style={{ marginBottom: 24 }}>
      <Text style={styles.sectionTitle}>{title}</Text>
      {callout ? <Callout>{callout}</Callout> : null}
      <Text style={styles.sectionBody}>{children}</Text>
    </View>
  );
}

function Callout({ children }: { children: React.ReactNode }) {
  return (
    <View style={styles.callout}>
      <Text style={styles.calloutBody}>{children}</Text>
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
  strong: { fontWeight: "700", color: "#1e293b" },
  callout: {
    backgroundColor: "#f8fafc",
    borderLeftWidth: 3,
    borderLeftColor: "#2a5298",
    borderRadius: 6,
    paddingHorizontal: 14,
    paddingVertical: 12,
    marginBottom: 24,
  },
  calloutBody: { color: "#334155", fontSize: 14, lineHeight: 22 },
  calloutStrong: { fontWeight: "700", color: "#1a3a6b" },
});
