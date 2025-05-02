import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { Form, FormControl, FormField, FormItem, FormMessage, } from "@/components/ui/form";
import { Play } from "lucide-react";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { useNavigate } from "react-router";
import api from "@/api";

const FormSchema = z.object({
  text: z.string(),
});

type FormData = z.infer<typeof FormSchema>;

const TextInputForm = () => {
	const form = useForm<FormData>({
    resolver: zodResolver(FormSchema),
    defaultValues: {
      text: "",
    },
  });

	const navigate = useNavigate();

  const onSubmit = async (data: FormData) => {
    try {
      const response = await api.post("/v1/documents", {
        source_type: "paste",
        text_content: data.text, 
      });
      console.log(response.data);

			navigate("/playback", { state: { apiResponse: response.data, inputText: data.text } });
    } catch (error) {
      console.error("Error posting prompt: ", error);
    }
  };

  return (
    <div className="flex flex-col w-full items-center space-y-8">
      <div className="flex flex-row w-[50%]">
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4 w-full">
            <FormField control={form.control} name="text" 
							render={({ field }) => (
                <FormItem>
                  <FormControl>
                    <Textarea placeholder="Type or paste a prompt..." {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <Button type="submit" variant="secondary">
              <Play />
              &nbsp;Start&nbsp;Listening
            </Button>
          </form>
        </Form>
      </div>
    </div>
  )
} 

export { TextInputForm }
